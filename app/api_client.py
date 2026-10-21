"""app/api_client.py — Cliente API Mercado Público con rate limiting, Retry-After y circuit breaker."""
from __future__ import annotations

import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Any, Dict, Iterator, List, Optional

import requests

try:
    from cachetools import TTLCache
except ImportError:  # pragma: no cover
    class TTLCache(dict):
        def __init__(self, maxsize=1, ttl=86_400):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl

from config import settings

logger = logging.getLogger(__name__)


class QuotaExhaustedException(Exception):
    """Cuota diaria local agotada o circuit breaker activo por 429s consecutivos."""


class ApiClientException(Exception):
    """Error de red / HTTP no recuperable tras reintentos."""


class RateLimitedException(ApiClientException):
    """Se agotaron los reintentos por 429; el servidor sigue pidiendo frenar."""


_TICKET_RE = re.compile(r"(?i)(ticket[=:\s]+)([^\s&\"']+)")


def redact_secrets(text: str, ticket: Optional[str] = None) -> str:
    if not text:
        return text
    out = _TICKET_RE.sub(r"\1[REDACTED]", str(text))
    if ticket and len(ticket) >= 8:
        out = out.replace(ticket, "[REDACTED]")
    return out


def _parse_retry_after(header_value: Optional[str]) -> Optional[float]:
    if not header_value:
        return None
    value = header_value.strip()
    try:
        seconds = float(value)
        if seconds >= 0:
            return min(seconds, 3600.0)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        if delta > 0:
            return min(delta, 3600.0)
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _backoff_with_jitter(
    attempt: int,
    base: float = 2.0,
    cap: float = 120.0,
    *,
    floor: float = 0.0,
) -> float:
    exp = min(cap, base * (2 ** attempt))
    wait = (exp / 2.0) + random.uniform(0, exp / 2.0)
    return max(floor, wait)


class RateLimiter:
    """Rate limit por segundo y por día + circuit breaker. Obj4: cuota en ApiQuotaDaily."""

    def __init__(
        self,
        per_second: float = 5,
        per_day: int = 10_000,
        circuit_threshold: int = 3,
        circuit_pause_sec: float = 900.0,
        *,
        persist: Optional[bool] = None,
    ):
        self.per_second = max(0.1, float(per_second))
        self.per_day = int(per_day)
        self.circuit_threshold = max(1, circuit_threshold)
        self.circuit_pause_sec = float(circuit_pause_sec)

        self._lock = Lock()
        self._sec_count = 0
        self._sec_reset = time.monotonic() + 1.0
        self._day_count = 0
        self._day_key = self._fecha_cl()
        self._quota_exhausted = False
        if persist is None:
            # API_QUOTA_PERSIST=0 en conftest / CI unitario
            persist = os.environ.get("API_QUOTA_PERSIST", "1").lower() not in (
                "0",
                "false",
                "no",
            )
        self._persist = bool(persist)

        self._consecutive_429_cycles = 0
        self._circuit_open_until: float = 0.0

        self._load_day_from_db()

    @property
    def day_count(self) -> int:
        with self._lock:
            self._maybe_reset_day()
            return self._day_count

    @property
    def circuit_open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._circuit_open_until

    @staticmethod
    def _fecha_cl() -> str:
        return datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d")

    def _load_day_from_db(self) -> None:
        if not self._persist:
            return
        try:
            from app.database import get_db
            from app.models import ApiQuotaDaily

            fecha = self._fecha_cl()
            with get_db() as db:
                row = db.query(ApiQuotaDaily).filter_by(fecha=fecha).first()
                if row:
                    self._day_count = int(row.requests or 0)
                    self._day_key = fecha
                    if self._day_count >= self.per_day:
                        self._quota_exhausted = True
        except Exception as e:
            logger.debug("RateLimiter: no se pudo cargar cuota BD (%s)", e)

    def _persist_day(self) -> None:
        if not self._persist:
            return
        try:
            from app.database import get_db
            from app.models import ApiQuotaDaily

            fecha = self._day_key
            with get_db() as db:
                row = db.query(ApiQuotaDaily).filter_by(fecha=fecha).first()
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                if row:
                    row.requests = self._day_count
                    row.limite = self.per_day
                    row.updated_at = now
                else:
                    db.add(
                        ApiQuotaDaily(
                            fecha=fecha,
                            requests=self._day_count,
                            limite=self.per_day,
                            updated_at=now,
                        )
                    )
        except Exception as e:
            logger.debug("RateLimiter: no se pudo persistir cuota (%s)", e)

    def _maybe_reset_day(self) -> None:
        key = self._fecha_cl()
        if key != self._day_key:
            self._day_key = key
            self._day_count = 0
            self._quota_exhausted = False
            self._load_day_from_db()

    def record_429_cycle_exhausted(self) -> None:
        with self._lock:
            self._consecutive_429_cycles += 1
            if self._consecutive_429_cycles >= self.circuit_threshold:
                self._circuit_open_until = time.monotonic() + self.circuit_pause_sec
                logger.warning(
                    "Circuit breaker ABIERTO: %d ciclos 429 seguidos. Pausa %.0fs.",
                    self._consecutive_429_cycles,
                    self.circuit_pause_sec,
                )

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_429_cycles = 0

    def acquire(self) -> None:
        sleep_for = 0.0
        with self._lock:
            now = time.monotonic()
            if now < self._circuit_open_until:
                remaining = self._circuit_open_until - now
                raise QuotaExhaustedException(
                    f"Circuit breaker activo ({remaining:.0f}s restantes tras 429s consecutivos)."
                )

            self._maybe_reset_day()
            if self._quota_exhausted or self._day_count >= self.per_day:
                self._quota_exhausted = True
                raise QuotaExhaustedException(
                    f"Cuota diaria de {self.per_day} requests agotada."
                )

            if now >= self._sec_reset:
                self._sec_count = 0
                self._sec_reset = now + 1.0

            if self._sec_count >= self.per_second:
                sleep_for = max(0.0, self._sec_reset - now)

            self._sec_count += 1
            self._day_count += 1
            self._persist_day()

        if sleep_for > 0:
            time.sleep(sleep_for)
        elif self.per_second <= 5:
            time.sleep(max(0.0, (1.0 / self.per_second) * 0.1))


class MercadoPublicoClient:
    BASE_URL = settings.API_BASE_URL.rstrip("/")
    _cache_regiones: TTLCache = TTLCache(maxsize=1, ttl=86_400)

    def __init__(
        self,
        ticket: Optional[str] = None,
        *,
        per_second: Optional[float] = None,
        per_day: Optional[int] = None,
        max_retries: Optional[int] = None,
    ):
        self.ticket = ticket or settings.TICKET_MERCADO_PUBLICO or ""
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.max_retries = max_retries if max_retries is not None else getattr(
            settings, "API_MAX_RETRIES", 5
        )
        self.rate_limiter = RateLimiter(
            per_second=per_second if per_second is not None else settings.API_RATE_PER_SECOND,
            per_day=per_day if per_day is not None else settings.API_RATE_PER_DAY,
            circuit_threshold=getattr(settings, "API_CIRCUIT_BREAKER_THRESHOLD", 3),
            circuit_pause_sec=getattr(settings, "API_CIRCUIT_BREAKER_PAUSE_SEC", 900.0),
        )

    def _safe_error(self, msg: str) -> str:
        return redact_secrets(msg, self.ticket)

    def _get(
        self,
        path: str,
        params: Optional[Dict] = None,
        max_retries: Optional[int] = None,
    ) -> Dict:
        if params is None:
            params = {}
        params = dict(params)
        params.setdefault("ticket", self.ticket)
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        retries = max_retries if max_retries is not None else self.max_retries
        last_status: Optional[int] = None
        consecutive_429_in_cycle = 0

        for attempt in range(retries):
            try:
                self.rate_limiter.acquire()
            except QuotaExhaustedException:
                raise

            try:
                resp = self.session.get(url, params=params, timeout=30)
                last_status = resp.status_code

                if resp.status_code == 429:
                    consecutive_429_in_cycle += 1
                    ra = _parse_retry_after(resp.headers.get("Retry-After"))
                    if ra is not None:
                        wait = max(2.0, ra + random.uniform(0, 1.5))
                    else:
                        wait = _backoff_with_jitter(attempt, base=5.0, cap=90.0, floor=2.0)
                    logger.warning(
                        "HTTP 429 (intento %d/%d). Esperando %.1fs\u2026",
                        attempt + 1,
                        retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                if resp.status_code in (500, 502, 503, 504):
                    wait = _backoff_with_jitter(attempt, base=3.0, cap=60.0)
                    logger.warning(
                        "HTTP %s (intento %d/%d). Esperando %.1fs\u2026",
                        resp.status_code,
                        attempt + 1,
                        retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                self.rate_limiter.record_success()
                return resp.json()

            except requests.exceptions.Timeout:
                if attempt < retries - 1:
                    time.sleep(_backoff_with_jitter(attempt, base=2.0, cap=30.0))
                    continue
                raise ApiClientException(
                    self._safe_error(f"Timeout tras {retries} intentos en {path}")
                )
            except requests.exceptions.RequestException as e:
                safe = self._safe_error(str(e))
                logger.error("RequestException en %s: %s", path, safe)
                if attempt < retries - 1:
                    time.sleep(_backoff_with_jitter(attempt, base=2.0, cap=30.0))
                    continue
                raise ApiClientException(safe) from None

        if last_status == 429 or consecutive_429_in_cycle > 0:
            self.rate_limiter.record_429_cycle_exhausted()
            raise RateLimitedException(
                self._safe_error(
                    f"Máx reintentos ({retries}) por 429 en {path}. Servidor pide frenar."
                )
            )
        raise ApiClientException(
            self._safe_error(f"Máx reintentos ({retries}) alcanzado para {path}")
        )

    def iter_licitaciones(
        self,
        fecha_desde=None,
        estado=None,
        codigo=None,
        tipo=None,
    ) -> Iterator[Dict]:
        """Una petición = un día calendario (`fecha` YYYY-MM-DD), no rango.

        Tras 429/cuota: sync_run incompleto (no lista vacía silenciosa).
        """
        from app.sync_state import start_sync_run, finish_sync_run, fecha_cl_hoy

        params: Dict[str, Any] = {}
        fecha = fecha_desde or fecha_cl_hoy()
        params["fecha"] = fecha
        if estado:
            params["estado"] = estado
        if codigo:
            params["codigo"] = codigo
        if tipo:
            params["tipo"] = tipo
        run_id = start_sync_run("licitaciones", fecha)
        items_ok = 0
        page = 1
        try:
            while True:
                params["pagina"] = page
                try:
                    data = self._get("publico/licitaciones.json", params.copy())
                except (QuotaExhaustedException, RateLimitedException) as e:
                    logger.error("Sync licitaciones interrumpida p%d: %s", page, e)
                    finish_sync_run(
                        run_id,
                        estado="incompleto",
                        motivo=type(e).__name__,
                        items_ok=items_ok,
                    )
                    return
                except ApiClientException as e:
                    logger.error("Error licitaciones p%d: %s", page, e)
                    finish_sync_run(
                        run_id, estado="error", motivo=str(e)[:300], items_ok=items_ok
                    )
                    return
                items: List[Dict] = data.get("Listado") or []
                if not items:
                    break
                for item in items:
                    item["_api_tipo"] = tipo or "licitacion"
                    items_ok += 1
                    yield item
                if len(items) < 1000:
                    break
                page += 1
            finish_sync_run(run_id, estado="completo", items_ok=items_ok)
        except GeneratorExit:
            finish_sync_run(
                run_id, estado="incompleto", motivo="generator_closed", items_ok=items_ok
            )
            raise

    def iter_ordenes_compra(
        self, fecha_desde=None, estado=None, codigo=None
    ) -> Iterator[Dict]:
        """Una petición = un día (`fecha`). 429/cuota \u2192 sync_run incompleto."""
        from app.sync_state import start_sync_run, finish_sync_run, fecha_cl_hoy

        params: Dict[str, Any] = {}
        fecha = fecha_desde or fecha_cl_hoy()
        params["fecha"] = fecha
        if estado:
            params["estado"] = estado
        if codigo:
            params["codigo"] = codigo
        run_id = start_sync_run("ordenes_compra", fecha)
        items_ok = 0
        page = 1
        try:
            while True:
                params["pagina"] = page
                try:
                    data = self._get("publico/ordenesdecompra.json", params.copy())
                except (QuotaExhaustedException, RateLimitedException) as e:
                    logger.error("Sync OC interrumpida p%d: %s", page, e)
                    finish_sync_run(
                        run_id,
                        estado="incompleto",
                        motivo=type(e).__name__,
                        items_ok=items_ok,
                    )
                    return
                except ApiClientException as e:
                    logger.error("Error OC p%d: %s", page, e)
                    finish_sync_run(
                        run_id, estado="error", motivo=str(e)[:300], items_ok=items_ok
                    )
                    return
                items: List[Dict] = data.get("Listado") or []
                if not items:
                    break
                for item in items:
                    item["_api_tipo"] = "orden_compra"
                    items_ok += 1
                    yield item
                if len(items) < 1000:
                    break
                page += 1
            finish_sync_run(run_id, estado="completo", items_ok=items_ok)
        except GeneratorExit:
            finish_sync_run(
                run_id, estado="incompleto", motivo="generator_closed", items_ok=items_ok
            )
            raise

    def iter_oportunidades(self, fecha_desde=None, estado=None) -> Iterator[Dict]:
        logger.warning(
            "compra_agil omitida: la API pública v1 no soporta tipo=CO (HTTP 400)."
        )
        return
        yield  # noqa: unreachable

    def get_licitacion_detalle(self, codigo: str) -> Optional[Dict]:
        try:
            data = self._get("publico/licitaciones.json", {"codigo": codigo})
            listado = data.get("Listado") or []
            return listado[0] if listado else None
        except (QuotaExhaustedException, RateLimitedException):
            raise
        except Exception as e:
            logger.error("Error detalle %s: %s", codigo, self._safe_error(str(e)))
            return None

    @staticmethod
    def to_api_date(dt: datetime) -> str:
        return dt.strftime("%d%m%Y")


def make_enrich_client(ticket: Optional[str] = None) -> MercadoPublicoClient:
    rate = getattr(settings, "API_ENRICH_RATE_PER_SECOND", 2.0)
    return MercadoPublicoClient(
        ticket=ticket,
        per_second=rate,
        per_day=settings.API_RATE_PER_DAY,
    )
