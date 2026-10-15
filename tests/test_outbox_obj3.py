"""Obj3: outbox idempotencia y claim básico (SQLite en memoria aislado)."""
from __future__ import annotations

import os
import uuid

# Forzar memoria: setdefault NO basta si .env ya definió DATABASE_URL
os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="module")
def outbox_bind():
    """Engine :memory: compartido (StaticPool) + SessionLocal rebind."""
    from app import database as dbmod
    from app.database import Base
    import app.models  # noqa: F401 — registra NotificationOutbox

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _connection_record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    return engine


@pytest.fixture(autouse=True)
def _clean_outbox(outbox_bind):
    from app.database import get_db
    from app.models import NotificationOutbox

    yield
    with get_db() as db:
        db.query(NotificationOutbox).delete()


def test_idempotency_key_unique(outbox_bind):
    from app.outbox import enqueue, make_idempotency_key
    from app.database import get_db
    from app.models import NotificationOutbox

    suffix = uuid.uuid4().hex
    key = make_idempotency_key("webhook", 1, f"https://example.com/hook/{suffix}", "r1")
    id1 = enqueue(
        canal="webhook",
        destino=f"https://example.com/hook/{suffix}",
        payload={"x": 1},
        alerta_id=1,
        idempotency_key=key,
    )
    id2 = enqueue(
        canal="webhook",
        destino=f"https://example.com/hook/{suffix}",
        payload={"x": 1},
        alerta_id=1,
        idempotency_key=key,
    )
    assert id1 is not None, "primer enqueue no debe devolver None"
    assert id2 is None, "segundo enqueue con misma key debe ser dedupe"
    with get_db() as db:
        n = db.query(NotificationOutbox).filter_by(idempotency_key=key).count()
    assert n == 1


def test_claim_batch_returns_pending(outbox_bind):
    from app.outbox import enqueue, make_idempotency_key, claim_batch

    suffix = uuid.uuid4().hex
    key = make_idempotency_key("email", None, f"a-{suffix}@b.cl", "claim")
    rid = enqueue(
        canal="email",
        destino=f"a-{suffix}@b.cl",
        payload={"tipo": "alerta", "entidad": {}},
        idempotency_key=key,
    )
    assert rid is not None
    ids = claim_batch(limit=50)
    assert isinstance(ids, list)
    assert rid in ids
