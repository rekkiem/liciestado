"""Obj3: outbox idempotencia y claim básico (SQLite)."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite://")

from app.database import init_db, get_db
from app.outbox import enqueue, make_idempotency_key, claim_batch
from app.models import NotificationOutbox


def setup_module():
    init_db()


def test_idempotency_key_unique():
    key = make_idempotency_key("webhook", 1, "https://example.com/hook", "r1")
    id1 = enqueue(
        canal="webhook",
        destino="https://example.com/hook",
        payload={"x": 1},
        alerta_id=1,
        idempotency_key=key,
    )
    id2 = enqueue(
        canal="webhook",
        destino="https://example.com/hook",
        payload={"x": 1},
        alerta_id=1,
        idempotency_key=key,
    )
    assert id1 is not None
    assert id2 is None
    with get_db() as db:
        n = db.query(NotificationOutbox).filter_by(idempotency_key=key).count()
    assert n == 1


def test_claim_batch_returns_pending():
    key = make_idempotency_key("email", None, "a@b.cl", "unique-test-claim")
    enqueue(
        canal="email",
        destino="a@b.cl",
        payload={"tipo": "alerta", "entidad": {}},
        idempotency_key=key,
    )
    ids = claim_batch(limit=50)
    assert isinstance(ids, list)
