"""Obj4: sync_run incompleto, cuota BD, enrich attempts, fecha param."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="module")
def db_bind():
    from app import database as dbmod
    from app.database import Base
    import app.models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    return engine


def test_quota_persists_to_db(db_bind):
    from app.api_client import RateLimiter, QuotaExhaustedException
    from app.database import get_db
    from app.models import ApiQuotaDaily
    from app.sync_state import fecha_cl_hoy

    rl = RateLimiter(per_second=100, per_day=3)
    rl.acquire()
    rl.acquire()
    rl.acquire()
    with pytest.raises(QuotaExhaustedException):
        rl.acquire()

    with get_db() as db:
        row = db.query(ApiQuotaDaily).filter_by(fecha=fecha_cl_hoy()).first()
        assert row is not None
        assert row.requests >= 3


def test_iter_licitaciones_incomplete_on_429(db_bind):
    from app.api_client import MercadoPublicoClient, RateLimitedException
    from app.database import get_db
    from app.models import SyncRun

    client = MercadoPublicoClient(ticket="T" * 36, per_second=100, per_day=1000)
    client.rate_limiter._persist = False

    def boom(*a, **k):
        raise RateLimitedException("429 max")

    client._get = boom  # type: ignore
    list(client.iter_licitaciones(fecha_desde="2026-10-14"))

    with get_db() as db:
        run = (
            db.query(SyncRun)
            .filter_by(kind="licitaciones", fecha="2026-10-14")
            .order_by(SyncRun.id.desc())
            .first()
        )
        assert run is not None
        assert run.estado == "incompleto"
        assert "RateLimited" in (run.motivo or "")


def test_fecha_param_sent(db_bind):
    from app.api_client import MercadoPublicoClient

    client = MercadoPublicoClient(ticket="T" * 36, per_second=100, per_day=1000)
    client.rate_limiter._persist = False
    seen = {}

    def fake_get(path, params=None, max_retries=None):
        seen["params"] = dict(params or {})
        return {"Listado": []}

    client._get = fake_get  # type: ignore
    list(client.iter_licitaciones(fecha_desde="2026-01-15"))
    assert seen["params"].get("fecha") == "2026-01-15"


def test_enrich_attempts_cap(db_bind):
    from app.database import get_db
    from app.models import LicitacionSnapshot
    from datetime import datetime, timezone

    with get_db() as db:
        db.add(
            LicitacionSnapshot(
                codigo="X-1",
                tipo="licitacion",
                datos={},
                enrich_attempts=5,
                fecha_sincronizacion=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.add(
            LicitacionSnapshot(
                codigo="X-2",
                tipo="licitacion",
                datos={},
                enrich_attempts=2,
                region=None,
                fecha_sincronizacion=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    with get_db() as db:
        q = db.query(LicitacionSnapshot).filter(
            LicitacionSnapshot.region.is_(None),
            LicitacionSnapshot.enrich_attempts < 5,
        )
        codes = [s.codigo for s in q.all()]
    assert "X-2" in codes
    assert "X-1" not in codes
