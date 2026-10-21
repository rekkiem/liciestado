"""Obj6: healthz, api/status shape, gold base upsert."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")
os.environ.setdefault("DASHBOARD_PASS", "testpass-not-default")
os.environ["API_QUOTA_PERSIST"] = "0"

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from werkzeug.security import generate_password_hash


@pytest.fixture(scope="module")
def app_client():
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

    from app.dashboard import create_app
    from app.models import User

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    with dbmod.SessionLocal() as db:
        u = User(
            email="obj6@test.cl",
            password_hash=generate_password_hash("secret"),
            nombre="Obj6",
            activo=True,
        )
        db.add(u)
        db.commit()

    client = application.test_client()
    return application, client


def test_healthz_no_auth(app_client):
    _, client = app_client
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json().get("status") == "ok"


def test_api_status_requires_auth(app_client):
    _, client = app_client
    r = client.get("/api/status")
    assert r.status_code in (302, 401, 403)


def test_api_status_authenticated(app_client):
    app, client = app_client
    with client.session_transaction() as sess:
        from app.database import SessionLocal
        from app.models import User
        with SessionLocal() as db:
            uid = db.query(User).filter_by(email="obj6@test.cl").one().id
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True

    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert "outbox" in body
    assert "pendientes" in body["outbox"]
    assert "fallidos" in body["outbox"]
    assert "cuota" in body
    assert "sync" in body


def test_gold_base_upsert(app_client):
    from app.database import SessionLocal
    from app.models import GoldBase

    with SessionLocal() as db:
        g = GoldBase(
            codigo="G-1",
            vertical="TI",
            titulo="Test",
            anotacion={"requisitos_obligatorios": ["x"]},
        )
        db.add(g)
        db.commit()
        row = db.query(GoldBase).filter_by(codigo="G-1").one()
        assert row.vertical == "TI"
        assert row.anotacion["requisitos_obligatorios"] == ["x"]
