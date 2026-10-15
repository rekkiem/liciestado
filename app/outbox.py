"""app/outbox.py — Cola durable de notificaciones (Obj3).

- idempotency_key UNIQUE
- estados: pendiente | procesando | enviado | fallido
- claim con lease (locked_at/locked_by) en la misma TX
- reaper de leases vencidos (>5 min)
- at-least-once + dedupe (X-LiciEstado-Idempotency-Key / HMAC)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import get_db, engine
from app.db_dialect import is_postgres
from app.models import AlertaGenerada, NotificationOutbox, UserConfig

logger = logging.getLogger(__name__)

_worker_thread: Optional[threading.Thread] = None
_stop = threading.Event()

LEASE_SECONDS = 300
_WORKER_ID = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_idempotency_key(canal: str, alerta_id: Optional[int], destino: str, extra: str = "") -> str:
    raw = f"{canal}|{alerta_id or 0}|{destino}|{extra}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def enqueue(
    *,
    canal: str,
    destino: str,
    payload: Dict[str, Any],
    user_id: Optional[int] = None,
    alerta_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    max_intentos: int = 5,
) -> Optional[int]:
    key = idempotency_key or make_idempotency_key(canal, alerta_id, destino)
    row = NotificationOutbox(
        user_id=user_id,
        alerta_id=alerta_id,
        canal=canal,
        destino=destino,
        payload_json=payload,
        idempotency_key=key,
        estado="pendiente",
        intentos=0,
        max_intentos=max_intentos,
        created_at=_now(),
        updated_at=_now(),
    )
    try:
        with get_db() as db:
            db.add(row)
            db.flush()
            rid = row.id
        logger.info("Outbox enqueue id=%s canal=%s key=%s…", rid, canal, key[:12])
        return rid
    except IntegrityError:
        logger.info("Outbox skip duplicate key=%s…", key[:12])
        return None


def _backoff_seconds(attempt: int) -> int:
    return min(30 * (2 ** max(0, attempt - 1)), 3600)


def reaper_expired_leases() -> int:
    cutoff = _now() - timedelta(seconds=LEASE_SECONDS)
    with engine.begin() as conn:
        res = conn.execute(
            text(
                """
                UPDATE notification_outbox
                   SET estado = 'pendiente',
                       locked_at = NULL,
                       locked_by = NULL,
                       updated_at = :now
                 WHERE estado = 'procesando'
                   AND locked_at IS NOT NULL
                   AND locked_at < :cutoff
                """
            ),
            {"now": _now(), "cutoff": cutoff},
        )
        n = res.rowcount or 0
    if n:
        logger.warning("Outbox reaper: %d leases vencidos \u2192 pendiente", n)
    return n


def claim_batch(limit: int = 10, worker_id: Optional[str] = None) -> List[int]:
    reaper_expired_leases()
    wid = worker_id or _WORKER_ID
    now = _now()
    ids: List[int] = []

    if is_postgres():
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id FROM notification_outbox
                    WHERE estado = 'pendiente'
                      AND (next_retry_at IS NULL OR next_retry_at <= :now)
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT :lim
                    """
                ),
                {"now": now, "lim": limit},
            ).fetchall()
            ids = [r[0] for r in rows]
            for i in ids:
                conn.execute(
                    text(
                        """
                        UPDATE notification_outbox
                           SET estado = 'procesando',
                               locked_at = :now,
                               locked_by = :wid,
                               updated_at = :now
                         WHERE id = :id AND estado = 'pendiente'
                        """
                    ),
                    {"now": now, "wid": wid, "id": i},
                )
    else:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id FROM notification_outbox
                    WHERE estado = 'pendiente'
                      AND (next_retry_at IS NULL OR next_retry_at <= :now)
                    ORDER BY id
                    LIMIT :lim
                    """
                ),
                {"now": now, "lim": limit},
            ).fetchall()
            ids = [r[0] for r in rows]
            for i in ids:
                conn.execute(
                    text(
                        """
                        UPDATE notification_outbox
                           SET estado = 'procesando',
                               locked_at = :now,
                               locked_by = :wid,
                               updated_at = :now
                         WHERE id = :id AND estado = 'pendiente'
                        """
                    ),
                    {"now": now, "wid": wid, "id": i},
                )
    return ids


def _sign_payload(body: bytes, secret: str, ts: str) -> str:
    msg = ts.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _resolve_webhook_secret(user_id: Optional[int]) -> str:
    if user_id:
        with get_db() as db:
            cfg = db.query(UserConfig).filter_by(user_id=user_id).first()
            if cfg and cfg.webhook_secret:
                return cfg.webhook_secret
    from config import settings

    return (getattr(settings, "WEBHOOK_HMAC_SECRET", "") or "").strip()


def _deliver_webhook(row) -> None:
    import requests as _requests
    from app.net_safety import validar_webhook_url

    ok_url, msg = validar_webhook_url(row.destino)
    if not ok_url:
        raise RuntimeError(f"URL bloqueada anti-SSRF: {msg}")

    secret = _resolve_webhook_secret(getattr(row, "user_id", None))
    if not secret:
        raise RuntimeError(
            "Webhook sin secreto HMAC: configura webhook_secret del usuario "
            "o WEBHOOK_HMAC_SECRET. No se env\u00eda sin firma."
        )

    body = json.dumps(row.payload_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {
        "Content-Type": "application/json",
        "X-LiciEstado-Event": "alerta",
        "X-LiciEstado-Timestamp": ts,
        "X-LiciEstado-Idempotency-Key": row.idempotency_key,
        "X-LiciEstado-Signature": _sign_payload(body, secret, ts),
    }
    resp = _requests.post(
        row.destino, data=body, headers=headers, timeout=15, allow_redirects=False
    )
    if not (200 <= resp.status_code < 300):
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


def _deliver_email(row) -> None:
    from app.email_service import enviar_payload_email

    enviar_payload_email(row.destino, row.payload_json)


def process_one(outbox_id: int, worker_id: Optional[str] = None) -> bool:
    wid = worker_id or _WORKER_ID
    with get_db() as db:
        row = db.query(NotificationOutbox).filter_by(id=outbox_id).first()
        if not row or row.estado != "procesando":
            return False
        if row.locked_by and row.locked_by != wid:
            if row.locked_at and row.locked_at > _now() - timedelta(seconds=LEASE_SECONDS):
                return False
        row.intentos = int(row.intentos or 0) + 1
        row.updated_at = _now()
        db.flush()
        canal = row.canal
        alerta_id = row.alerta_id
        intentos = row.intentos
        max_i = row.max_intentos
        destino = row.destino
        payload = dict(row.payload_json or {})
        user_id = row.user_id
        idem = row.idempotency_key

    class _Snap:
        pass

    snap = _Snap()
    snap.destino = destino
    snap.payload_json = payload
    snap.user_id = user_id
    snap.idempotency_key = idem
    snap.alerta_id = alerta_id

    try:
        if canal == "webhook":
            _deliver_webhook(snap)
        elif canal == "email":
            _deliver_email(snap)
        else:
            raise RuntimeError(f"canal desconocido: {canal}")
    except Exception as e:
        err = str(e)[:500]
        logger.warning("Outbox id=%s fallo intento=%s: %s", outbox_id, intentos, err)
        with get_db() as db:
            row = db.query(NotificationOutbox).filter_by(id=outbox_id).first()
            if not row:
                return False
            row.last_error = err
            row.updated_at = _now()
            row.locked_at = None
            row.locked_by = None
            if intentos >= max_i:
                row.estado = "fallido"
            else:
                row.estado = "pendiente"
                row.next_retry_at = _now() + timedelta(seconds=_backoff_seconds(intentos))
        return False

    with get_db() as db:
        row = db.query(NotificationOutbox).filter_by(id=outbox_id).first()
        if not row:
            return False
        row.estado = "enviado"
        row.enviado_at = _now()
        row.updated_at = _now()
        row.last_error = None
        row.locked_at = None
        row.locked_by = None
        if canal == "email":
            ids = []
            if alerta_id:
                ids.append(alerta_id)
            extra = (row.payload_json or {}).get("alerta_ids") or []
            ids.extend(int(x) for x in extra if x is not None)
            if ids:
                db.query(AlertaGenerada).filter(AlertaGenerada.id.in_(ids)).update(
                    {"enviado_email": True}, synchronize_session=False
                )
    logger.info("Outbox id=%s enviado canal=%s", outbox_id, canal)
    return True


def process_pending(limit: int = 20, worker_id: Optional[str] = None) -> int:
    ids = claim_batch(limit=limit, worker_id=worker_id)
    ok = 0
    for i in ids:
        if process_one(i, worker_id=worker_id):
            ok += 1
    return ok


def _worker_loop():
    logger.info("Outbox worker arrancado id=%s", _WORKER_ID)
    while not _stop.is_set():
        try:
            n = process_pending(limit=10, worker_id=_WORKER_ID)
            if n == 0:
                _stop.wait(2.0)
        except Exception:
            logger.exception("Outbox worker error")
            _stop.wait(5.0)


def iniciar_worker_outbox():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop.clear()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="outbox-worker")
    _worker_thread.start()
    logger.info("Outbox worker iniciado")
