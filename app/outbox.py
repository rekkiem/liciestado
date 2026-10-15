"""app/outbox.py — Cola durable de notificaciones (Obj3).

- idempotency_key UNIQUE
- estados: pendiente | enviado | fallido
- claim: SELECT … FOR UPDATE SKIP LOCKED (Postgres) / BEGIN IMMEDIATE (SQLite)
- reintentos con backoff exponencial
- HMAC SHA-256 en webhooks (X-LiciEstado-Signature + Timestamp)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
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


def _now() -> datetime:
    return datetime.utcnow()


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
    """Inserta fila pendiente. Si la key ya existe, no duplica."""
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


def claim_batch(limit: int = 10) -> List[int]:
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
                    text("UPDATE notification_outbox SET updated_at = :now WHERE id = :id"),
                    {"now": now, "id": i},
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
            if ids:
                conn.execute(
                    text(
                        f"UPDATE notification_outbox SET updated_at = :now WHERE id IN ({','.join(str(i) for i in ids)})"
                    ),
                    {"now": now},
                )
    return ids


def _sign_payload(body: bytes, secret: str, ts: str) -> str:
    msg = ts.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def _deliver_webhook(row: NotificationOutbox) -> None:
    import requests as _requests
    from app.net_safety import validar_webhook_url

    ok_url, msg = validar_webhook_url(row.destino)
    if not ok_url:
        raise RuntimeError(f"URL bloqueada anti-SSRF: {msg}")

    body = json.dumps(row.payload_json, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {
        "Content-Type": "application/json",
        "X-LiciEstado-Event": "alerta",
        "X-LiciEstado-Timestamp": ts,
        "X-LiciEstado-Idempotency-Key": row.idempotency_key,
    }
    secret = None
    if row.user_id:
        with get_db() as db:
            cfg = db.query(UserConfig).filter_by(user_id=row.user_id).first()
            if cfg and cfg.webhook_secret:
                secret = cfg.webhook_secret
    if not secret:
        from config import settings

        secret = getattr(settings, "WEBHOOK_HMAC_SECRET", "") or ""
    if secret:
        headers["X-LiciEstado-Signature"] = _sign_payload(body, secret, ts)

    resp = _requests.post(
        row.destino, data=body, headers=headers, timeout=15, allow_redirects=False
    )
    if not (200 <= resp.status_code < 300):
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


def _deliver_email(row: NotificationOutbox) -> None:
    from app.email_service import enviar_payload_email

    enviar_payload_email(row.destino, row.payload_json)


def process_one(outbox_id: int) -> bool:
    with get_db() as db:
        row = db.query(NotificationOutbox).filter_by(id=outbox_id).first()
        if not row or row.estado != "pendiente":
            return False
        row.intentos = int(row.intentos or 0) + 1
        row.updated_at = _now()
        db.flush()
        canal = row.canal
        alerta_id = row.alerta_id
        intentos = row.intentos
        max_i = row.max_intentos

    try:
        with get_db() as db:
            row = db.query(NotificationOutbox).filter_by(id=outbox_id).first()
            if not row:
                return False
            if canal == "webhook":
                _deliver_webhook(row)
            elif canal == "email":
                _deliver_email(row)
            else:
                raise RuntimeError(f"canal desconocido: {canal}")

            row.estado = "enviado"
            row.enviado_at = _now()
            row.updated_at = _now()
            row.last_error = None
            if alerta_id and canal == "email":
                db.query(AlertaGenerada).filter_by(id=alerta_id).update(
                    {"enviado_email": True}, synchronize_session=False
                )
        logger.info("Outbox id=%s enviado canal=%s", outbox_id, canal)
        return True
    except Exception as e:
        err = str(e)[:500]
        logger.warning("Outbox id=%s fallo intento=%s: %s", outbox_id, intentos, err)
        with get_db() as db:
            row = db.query(NotificationOutbox).filter_by(id=outbox_id).first()
            if not row:
                return False
            row.last_error = err
            row.updated_at = _now()
            if intentos >= max_i:
                row.estado = "fallido"
            else:
                row.estado = "pendiente"
                row.next_retry_at = _now() + timedelta(seconds=_backoff_seconds(intentos))
        return False


def process_pending(limit: int = 20) -> int:
    ids = claim_batch(limit=limit)
    ok = 0
    for i in ids:
        if process_one(i):
            ok += 1
    return ok


def _worker_loop():
    logger.info("Outbox worker arrancado")
    while not _stop.is_set():
        try:
            n = process_pending(limit=10)
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
