"""Smoke routes + API existence + SSRF + alerta insert."""
from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from werkzeug.security import generate_password_hash


def _reset_db_modules():
    for mod in ("config", "app.database", "app.crypto", "app.models"):
        if mod in sys.modules:
            del sys.modules[mod]


@pytest.fixture()
def app():
    """App Flask + schema en SQLite memoria compartida (StaticPool)."""
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")
    os.environ.setdefault("DASHBOARD_PASS", "testpass-not-default")
    os.environ.setdefault("TICKET_MERCADO_PUBLICO", "TEST_TICKET_ONLY")
    os.environ.setdefault(
        "FERNET_KEY", "nxnwbct6-gajdCxxUTPWtgAdrdQhtErWQkERhrABPpg="
    )
    os.environ["API_QUOTA_PERSIST"] = "0"
    _reset_db_modules()

    from app.database import Base
    import app.models  # noqa: F401
    import app.database as dbmod

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

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    yield application
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def user_client(app):
    from app.database import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        u = db.query(User).filter_by(email="smoke@test.com").first()
        if not u:
            u = User(
                email="smoke@test.com",
                password_hash=generate_password_hash("pass12345"),
                plan="pro",
                activo=True,
                is_admin=True,
            )
            db.add(u)
            db.commit()
    c = app.test_client()
    c.post(
        "/login",
        data={"email": "smoke@test.com", "password": "pass12345"},
        follow_redirects=True,
    )
    return c


def test_authenticated_routes_no_500(user_client):
    for path in ["/", "/dashboard", "/reglas", "/licitaciones", "/analytics", "/configuracion"]:
        r = user_client.get(path, follow_redirects=True)
        assert r.status_code != 500, f"{path} returned 500"
        assert r.status_code in (200, 302), f"{path} -> {r.status_code}"


def test_api_routes_exist(user_client):
    for path in ["/api/analytics/resumen", "/api/status", "/licitaciones/export.csv"]:
        r = user_client.get(path, follow_redirects=True)
        assert r.status_code != 404, f"{path} missing (404)"
        assert r.status_code != 500, f"{path} 500"


def test_webhook_rejects_ssrf():
    from app.net_safety import validar_webhook_url

    attacks = [
        "https://169.254.169.254/x",
        "https://[::ffff:127.0.0.1]/x",
        "https://127.1/x",
        "https://2130706433/x",
    ]
    for url in attacks:
        ok, msg = validar_webhook_url(url)
        assert ok is False, f"should block {url}: {msg}"


def test_alerta_insert_default_tipo_entidad(app):
    """Inserta alerta; tipo_entidad usa default 'licitacion' si no se pasa."""
    from app.database import SessionLocal
    from app.models import User, ReglaUsuario, AlertaGenerada

    with SessionLocal() as db:
        u = db.query(User).filter_by(email="smoke@test.com").first()
        if not u:
            u = User(
                email="smoke2@test.com",
                password_hash=generate_password_hash("x"),
                plan="free",
                activo=True,
            )
            db.add(u)
            db.flush()
        r = ReglaUsuario(
            user_id=u.id,
            nombre_regla="r1",
            tipo_entidad="licitacion",
            filtros={},
            email_destino="a@test.com",
            activa=True,
        )
        db.add(r)
        db.flush()
        a = AlertaGenerada(
            user_id=u.id,
            regla_id=r.id,
            entidad_id="CODE-SMOKE",
            datos_resumen={"titulo": "t"},
            enviado_email=False,
        )
        db.add(a)
        db.flush()
        assert a.id is not None
        assert a.tipo_entidad == "licitacion"
        assert getattr(a, "mostrado_dashboard", True) is True
