"""Obj3: outbox idempotencia, lease claim, reaper (SQLite StaticPool)."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="module")
def outbox_bind():
    from app import database as dbmod
    from app.database import Base
    import app.models  # noqa: F401

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
    import app.db_dialect as dia

    dia.is_postgres = lambda: False  # type: ignore
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
    assert id1 is not None
    assert id2 is None
    with get_db() as db:
        n = db.query(NotificationOutbox).filter_by(idempotency_key=key).count()
    assert n == 1


def test_claim_batch_sets_procesando(outbox_bind):
    from app.outbox import enqueue, make_idempotency_key, claim_batch
    from app.database import get_db
    from app.models import NotificationOutbox

    suffix = uuid.uuid4().hex
    key = make_idempotency_key("email", None, f"a-{suffix}@b.cl", "claim")
    rid = enqueue(
        canal="email",
        destino=f"a-{suffix}@b.cl",
        payload={"tipo": "alerta", "entidad": {}},
        idempotency_key=key,
    )
    assert rid is not None
    ids = claim_batch(limit=50, worker_id="w-test")
    assert rid in ids
    with get_db() as db:
        row = db.query(NotificationOutbox).filter_by(id=rid).first()
        assert row.estado == "procesando"
        assert row.locked_by == "w-test"


def test_double_worker_single_claim(outbox_bind):
    from app.outbox import enqueue, make_idempotency_key, claim_batch

    suffix = uuid.uuid4().hex
    key = make_idempotency_key("email", None, f"dw-{suffix}@b.cl", "dw")
    rid = enqueue(
        canal="email",
        destino=f"dw-{suffix}@b.cl",
        payload={"tipo": "alerta", "entidad": {}},
        idempotency_key=key,
    )
    results = []

    def _claim(wid):
        results.append(claim_batch(limit=10, worker_id=wid))

    t1 = threading.Thread(target=_claim, args=("worker-A",))
    t2 = threading.Thread(target=_claim, args=("worker-B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    claimed = [i for batch in results for i in batch]
    assert claimed.count(rid) == 1, f"doble claim: {results}"


def test_reaper_expired_lease(outbox_bind):
    from app.outbox import (
        enqueue,
        make_idempotency_key,
        claim_batch,
        reaper_expired_leases,
        LEASE_SECONDS,
        _now,
    )
    from app.database import get_db, engine
    from app.models import NotificationOutbox

    suffix = uuid.uuid4().hex
    key = make_idempotency_key("email", None, f"rp-{suffix}@b.cl", "rp")
    rid = enqueue(
        canal="email",
        destino=f"rp-{suffix}@b.cl",
        payload={"tipo": "alerta", "entidad": {}},
        idempotency_key=key,
    )
    claim_batch(limit=1, worker_id="old-worker")
    old = _now() - timedelta(seconds=LEASE_SECONDS + 10)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE notification_outbox SET locked_at = :old WHERE id = :id"),
            {"old": old, "id": rid},
        )
    n = reaper_expired_leases()
    assert n >= 1
    with get_db() as db:
        row = db.query(NotificationOutbox).filter_by(id=rid).first()
        assert row.estado == "pendiente"
        assert row.locked_by is None
