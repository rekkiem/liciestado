"""app/api_client.py — Cliente API Mercado Público con rate limiting y paginación."""
from __future__ import annotations
import logging, time
from datetime import datetime
from threading import Lock
from typing import Any, Dict, Iterator, List, Optional
import requests
from cachetools import TTLCache
from config import settings

logger = logging.getLogger(__name__)

class QuotaExhaustedException(Exception): pass
class ApiClientException(Exception): pass

class RateLimiter:
    def __init__(self, per_second=5, per_day=10_000):
        self.per_second = per_second; self.per_day = per_day
        self._lock = Lock(); self._sec_count = 0
        self._sec_reset = time.monotonic() + 1.0
        self._day_count = 0; self._day_reset = time.monotonic() + 86_400.0
        self._quota_exhausted = False

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            if now >= self._day_reset:
                self._day_count = 0; self._day_reset = now + 86_400.0; self._quota_exhausted = False
            if self._quota_exhausted or self._day_count >= self.per_day:
                self._quota_exhausted = True
                raise QuotaExhaustedException(f"Cuota diaria de {self.per_day} requests agotada.")
            if now >= self._sec_reset:
                self._sec_count = 0; self._sec_reset = now + 1.0
            if self._sec_count >= self.per_second:
                sleep_ms = self._sec_reset - now
                if sleep_ms > 0: time.sleep(sleep_ms)
                self._sec_count = 0; self._sec_reset = time.monotonic() + 1.0
            self._sec_count += 1; self._day_count += 1

class MercadoPublicoClient:
    BASE_URL = settings.API_BASE_URL.rstrip("/")
    _cache_regiones: TTLCache = TTLCache(maxsize=1, ttl=86_400)

    def __init__(self, ticket: Optional[str] = None):
        self.ticket = ticket or settings.TICKET_MERCADO_PUBLICO
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.rate_limiter = RateLimiter(
            per_second=settings.API_RATE_PER_SECOND,
            per_day=settings.API_RATE_PER_DAY,
        )

    def _get(self, path: str, params: Optional[Dict] = None, max_retries=3) -> Dict:
        if params is None: params = {}
        params.setdefault("ticket", self.ticket)
        url = f"{self.BASE_URL}/{path.lstrip('/')}"
        for attempt in range(max_retries):
            try:
                self.rate_limiter.acquire()
            except QuotaExhaustedException:
                raise
            try:
                resp = self.session.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** attempt * 5
                    logger.warning("HTTP 429. Esperando %ss…", wait); time.sleep(wait); continue
                if resp.status_code in (500, 502, 503, 504):
                    wait = 2 ** attempt * 10
                    logger.warning("HTTP %s. Esperando %ss…", resp.status_code, wait); time.sleep(wait); continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.Timeout:
                if attempt < max_retries - 1: time.sleep(2 ** attempt * 3)
            except requests.exceptions.RequestException as e:
                logger.error("RequestException en %s: %s", url, e)
                if attempt < max_retries - 1: time.sleep(2 ** attempt * 2)
                else: raise ApiClientException(str(e)) from e
        raise ApiClientException(f"Máx reintentos ({max_retries}) alcanzado para {url}")

    def iter_licitaciones(self, fecha_desde=None, estado=None, codigo=None, tipo=None) -> Iterator[Dict]:
        params: Dict[str, Any] = {}
        if fecha_desde: params["fecha"] = fecha_desde
        if estado: params["estado"] = estado
        if codigo: params["codigo"] = codigo
        if tipo: params["tipo"] = tipo
        page = 1
        while True:
            params["pagina"] = page
            try:
                data = self._get("publico/licitaciones.json", params.copy())
            except (QuotaExhaustedException, ApiClientException) as e:
                logger.error("Error licitaciones p%d: %s", page, e); return
            items: List[Dict] = data.get("Listado") or []
            if not items: break
            for item in items:
                item["_api_tipo"] = tipo or "licitacion"; yield item
            if len(items) < 1000: break
            page += 1

    def iter_ordenes_compra(self, fecha_desde=None, estado=None, codigo=None) -> Iterator[Dict]:
        params: Dict[str, Any] = {}
        if fecha_desde: params["fecha"] = fecha_desde
        if estado: params["estado"] = estado
        if codigo: params["codigo"] = codigo
        page = 1
        while True:
            params["pagina"] = page
            try:
                data = self._get("publico/ordenesdecompra.json", params.copy())
            except (QuotaExhaustedException, ApiClientException) as e:
                logger.error("Error OC p%d: %s", page, e); return
            items: List[Dict] = data.get("Listado") or []
            if not items: break
            for item in items:
                item["_api_tipo"] = "orden_compra"; yield item
            if len(items) < 1000: break
            page += 1

    def iter_oportunidades(self, fecha_desde=None, estado=None) -> Iterator[Dict]:
        """Compra ágil (tipo=CO) — no soportada por la API pública v1."""
        logger.warning("compra_agil omitida: la API pública v1 no soporta tipo=CO (HTTP 400).")
        return; yield  # noqa

    def get_licitacion_detalle(self, codigo: str):
        try:
            data = self._get("publico/licitaciones.json", {"codigo": codigo})
            listado = data.get("Listado") or []
            return listado[0] if listado else None
        except Exception as e:
            logger.error("Error detalle %s: %s", codigo, e); return None

    @staticmethod
    def to_api_date(dt: datetime) -> str:
        return dt.strftime("%d%m%Y")
