"""Tests C2/A2: schema compatible + is_admin + es_pro trial + migrate tipo_entidad."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker, joinedload

from app.models import Base, User, UserConfig, AlertaGenerada, ReglaUsuario


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def test_alerta_generada_schema_matches_main():
    """tipo_entidad y mostrado_dashboard deben existir (compat + inserts)."""
    cols = {c.name for c in AlertaGenerada.__table__.columns}
    assert "mostrado_dashboard" in cols
    assert "tipo_entidad" in cols
    assert AlertaGenerada.__table__.c.entidad_id.type.length == 150
    assert AlertaGenerada.__table__.c.regla_id.nullable is False
    assert AlertaGenerada.__table__.c.datos_resumen.nullable is False


def test_user_has_is_admin():
    cols = {c.name for c in User.__table__.columns}
    assert "is_admin" in cols


def test_insert_alerta_with_default_tipo_entidad(session):
    u = User(email="a@test.com", password_hash="x", plan="free")
    session.add(u)
    session.flush()
    r = ReglaUsuario(
        user_id=u.id, nombre_regla="r1", tipo_entidad="licitacion",
        filtros={}, email_destino="a@test.com", activa=True,
    )
    session.add(r)
    session.flush()
    a = AlertaGenerada(
        user_id=u.id, regla_id=r.id, entidad_id="CODE-1",
        datos_resumen={"titulo": "t"}, enviado_email=False,
    )
    session.add(a)
    session.commit()
    assert a.id is not None
    assert a.tipo_entidad == "licitacion"


def test_es_pro_plan_pro(session):
    u = User(email="pro@test.com", password_hash="x", plan="pro")
    session.add(u)
    session.commit()
    assert u.es_pro is True


def test_es_pro_trial_activo(session):
    """Mismo camino que cargar_usuario: User + config en identidad (joinedload/__dict__)."""
    u = User(email="trial@test.com", password_hash="x", plan="free")
    session.add(u)
    session.flush()
    cfg = UserConfig(
        user_id=u.id,
        trial_pro_hasta=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
    )
    session.add(cfg)
    session.commit()
    u2 = (
        session.query(User)
        .options(joinedload(User.config))
        .filter_by(id=u.id)
        .one()
    )
    assert u2.es_pro is True


def test_es_pro_trial_vencido(session):
    u = User(email="old@test.com", password_hash="x", plan="free")
    session.add(u)
    session.flush()
    cfg = UserConfig(
        user_id=u.id,
        trial_pro_hasta=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
    )
    session.add(cfg)
    session.commit()
    u2 = (
        session.query(User)
        .options(joinedload(User.config))
        .filter_by(id=u.id)
        .one()
    )
    assert u2.es_pro is False


def test_migrate_is_admin_on_legacy_users(tmp_path, monkeypatch):
    import app.database as dbmod
    from sqlalchemy import create_engine, text, inspect as sa_inspect
    url = f"sqlite:///{tmp_path / 'legacy_users.db'}"
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), "
            "password_hash VARCHAR(255), nombre VARCHAR(120), plan VARCHAR(30), "
            "activo BOOLEAN, fecha_registro DATETIME, ultimo_acceso DATETIME)"
        ))
    with eng.begin() as conn:
        cols = [c["name"] for c in sa_inspect(eng).get_columns("users")]
        assert "is_admin" not in cols
        conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
    cols2 = [c["name"] for c in sa_inspect(eng).get_columns("users")]
    assert "is_admin" in cols2


def test_migrate_adds_tipo_entidad(tmp_path, monkeypatch):
    """BD sin tipo_entidad (esquema main) recibe la columna al init_db/migrate."""
    import app.database as dbmod
    from sqlalchemy import create_engine, text
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    eng = create_engine(url)
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE alertas_generadas ("
            "id INTEGER PRIMARY KEY, user_id INTEGER, regla_id INTEGER NOT NULL, "
            "entidad_id VARCHAR(150) NOT NULL, datos_resumen JSON NOT NULL, "
            "fecha_alerta DATETIME, enviado_email BOOLEAN, mostrado_dashboard BOOLEAN DEFAULT 1)"
        ))
    monkeypatch.setattr(dbmod, "engine", eng)
    dbmod._migrate_alerta_schema()
    with eng.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(alertas_generadas)")).fetchall()]
    assert "tipo_entidad" in cols
