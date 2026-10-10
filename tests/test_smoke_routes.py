"""Smoke tests Fase 0: rutas autenticadas, APIs, reglas, webhook anti-SSRF."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture
def app(tmp_path, monkeypatch):
    dbfile = tmp_path / "smoke.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    monkeypatch.delenv("FLASK_ENV", raising=False)
    from config import settings
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret-key-not-default")
    monkeypatch.setattr(settings, "DASHBOARD_PASS", "test-pass-not-default")
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{dbfile}")

    from app.database import init_db, engine, Base
    from app import models  # noqa
    Base.metadata.drop_all(bind=engine)
    init_db()

    from app.dashboard import create_app
    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user_client(client, app):
    from app.auth import registrar_usuario
    from app.models import User
    from app.database import get_db
    try:
        registrar_usuario("smoke@test.com", "password123", "Smoke")
    except Exception:
        pass
    with get_db() as db:
        u = db.query(User).filter_by(email="smoke@test.com").first()
        if u:
            db.query(User).filter_by(id=u.id).update({"plan": "pro", "is_admin": True})
    client.post("/login", data={"email": "smoke@test.com", "password": "password123"}, follow_redirects=False)
    return client


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


def test_alerta_insert_without_tipo_entidad():
    from app.database import get_db
    from app.models import User, ReglaUsuario, AlertaGenerada
    with get_db() as db:
        u = db.query(User).filter_by(email="smoke@test.com").first()
        if not u:
            u = User(email="smoke2@test.com", password_hash="x", plan="free")
            db.add(u)
            db.flush()
        r = ReglaUsuario(
            user_id=u.id, nombre_regla="r1", tipo_entidad="licitacion",
            filtros={}, email_destino="a@test.com", activa=True,
        )
        db.add(r)
        db.flush()
        a = AlertaGenerada(
            user_id=u.id, regla_id=r.id, entidad_id="CODE-SMOKE",
            datos_resumen={"titulo": "t"}, enviado_email=False,
        )
        db.add(a)
        db.flush()
        assert a.id is not None
        assert getattr(a, "mostrado_dashboard", True) is True
