"""Smoke routes + API existence + SSRF + alerta insert."""
import os
import pytest


@pytest.fixture()
def app():
    # Forzar sqlite: setdefault no pisa DATABASE_URL de la shell (PG real o URL falsa de otros tests)
    os.environ["DATABASE_URL"] = "sqlite://"
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")
    os.environ.setdefault("DASHBOARD_PASS", "testpass-not-default")
    os.environ.setdefault("TICKET_MERCADO_PUBLICO", "TEST_TICKET_ONLY")
    os.environ.setdefault(
        "FERNET_KEY", "nxnwbct6-gajdCxxUTPWtgAdrdQhtErWQkERhrABPpg="
    )
    # Reiniciar settings/engine si quedaron cacheados con otra URL
    for mod in ("config", "app.database", "app.crypto"):
        if mod in __import__("sys").modules:
            del __import__("sys").modules[mod]
    from app.database import init_db
    from app.dashboard import create_app
    init_db()
    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def user_client(app):
    from app.database import get_db
    from app.models import User
    from werkzeug.security import generate_password_hash
    with get_db() as db:
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


def test_alerta_insert_default_tipo_entidad():
    """Inserta alerta; tipo_entidad usa default 'licitacion' si no se pasa."""
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
        assert a.tipo_entidad == "licitacion"
        assert getattr(a, "mostrado_dashboard", True) is True
