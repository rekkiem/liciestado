"""
app/webhook_service.py — Envío de webhooks por usuario.

Entrega notificaciones POST a URLs configuradas por el usuario
cuando se genera una nueva alerta. Incluye retry y logging.
"""
from __future__ import annotations
import json, logging, threading, queue
from datetime import datetime, timezone
from typing import Dict, Optional
import requests as _requests
from app.database import get_db
from app.models import WebhookLog

logger = logging.getLogger(__name__)
_webhook_queue: queue.Queue = queue.Queue()


def _payload(regla_nombre: str, entidad: Dict, user_id: int) -> Dict:
    return {
        "evento":       "nueva_alerta",
        "plataforma":   "LiciEstado",
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "user_id":      user_id,
        "regla":        regla_nombre,
        "licitacion": {
            "codigo":   entidad.get("codigo"),
            "titulo":   entidad.get("titulo"),
            "organismo": entidad.get("organismo"),
            "monto_clp": entidad.get("monto_clp"),
            "region":   entidad.get("region"),
            "tipo":     entidad.get("tipo", "licitacion"),
            "link":     entidad.get("link_detalle") or entidad.get("link"),
        },
    }


def _enviar_webhook(url: str, payload: Dict, user_id: int,
                    alerta_id: Optional[int] = None, max_retries: int = 3) -> bool:
    for attempt in range(max_retries):
        try:
            from app.net_safety import validar_webhook_url
            ok_url, msg = validar_webhook_url(url)
            if not ok_url:
                logger.warning("Webhook bloqueado anti-SSRF: %s (%s)", url, msg)
                return False
            resp = _requests.post(
                url, json=payload, timeout=10, allow_redirects=False,
                headers={"Content-Type": "application/json", "X-LiciEstado-Event": "alerta"},
            )
            ok = 200 <= resp.status_code < 300
            with get_db() as db:
                db.add(WebhookLog(
                    user_id=user_id, alerta_id=alerta_id, url=url,
                    status_code=resp.status_code, ok=ok,
                    intentos=attempt + 1, payload_json=payload,
                ))
            if ok:
                logger.info("Webhook OK user_id=%d → %s", user_id, url)
                return True
            logger.warning("Webhook HTTP %d (intento %d) → %s", resp.status_code, attempt+1, url)
        except Exception as e:
            logger.warning("Webhook error (intento %d): %s", attempt+1, e)
    return False


def encolar_webhook(url: str, regla_nombre: str, entidad: Dict,
                    user_id: int, alerta_id: Optional[int] = None):
    if not url:
        return
    _webhook_queue.put({
        "url": url, "regla_nombre": regla_nombre, "entidad": entidad,
        "user_id": user_id, "alerta_id": alerta_id,
    })


def _worker_loop():
    logger.info("Worker de webhooks arrancado.")
    while True:
        try:
            item = _webhook_queue.get(timeout=5)
            if item is None:
                break
            _enviar_webhook(
                url=item["url"],
                payload=_payload(item["regla_nombre"], item["entidad"], item["user_id"]),
                user_id=item["user_id"],
                alerta_id=item.get("alerta_id"),
            )
            _webhook_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.exception("Error worker webhook: %s", e)


_worker_thread: Optional[threading.Thread] = None


def iniciar_worker_webhook():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="webhook-worker")
    _worker_thread.start()
    logger.info("Worker de webhooks iniciado.")
