"""app/webhook_service.py — Webhooks vía outbox durable (Obj3)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _payload(regla_nombre: str, entidad: Dict, user_id: int) -> Dict:
    return {
        "evento": "nueva_alerta",
        "plataforma": "LiciEstado",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "regla": regla_nombre,
        "licitacion": {
            "codigo": entidad.get("codigo"),
            "titulo": entidad.get("titulo"),
            "organismo": entidad.get("organismo"),
            "monto_clp": entidad.get("monto_clp"),
            "region": entidad.get("region"),
            "tipo": entidad.get("tipo", "licitacion"),
            "link": entidad.get("link_detalle") or entidad.get("link"),
        },
    }


def encolar_webhook(
    url: str,
    regla_nombre: str,
    entidad: Dict,
    user_id: int,
    alerta_id: Optional[int] = None,
) -> None:
    from app.outbox import enqueue, make_idempotency_key

    payload = _payload(regla_nombre, entidad, user_id)
    codigo = (entidad or {}).get("codigo") or ""
    key = make_idempotency_key("webhook", alerta_id, url, f"{regla_nombre}|{codigo}")
    enqueue(
        canal="webhook",
        destino=url,
        payload=payload,
        user_id=user_id,
        alerta_id=alerta_id,
        idempotency_key=key,
    )


def iniciar_worker_webhook():
    """Compat: el worker real es outbox."""
    from app.outbox import iniciar_worker_outbox

    iniciar_worker_outbox()
