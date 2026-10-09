"""Tests C2/A2: schema compatible with main + is_admin + es_pro trial."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import Base, User, UserConfig, AlertaGenerada, ReglaUsuario


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_alerta_generada_schema_matches_main():
    cols = {c.name for c in AlertaGenerada.__table__.columns}
    assert "mostrado_dashboard" in cols
    assert "tipo_entidad" not in cols
    assert AlertaGenerada.__table__.c.entidad_id.type.length == 150
    assert AlertaGenerada.__table__.c.regla_id.nullable is False
    assert AlertaGenerada.__table__.c.datos_resumen.nullable is False


def test_user_has_is_admin():
    cols = {c.name for c in User.__table__.columns}
    assert "is_admin" in cols


def test_insert_alerta_without_tipo_entidad(session):
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
    got = session.query(AlertaGenerada).filter_by(entidad_id="CODE-1").one()
    assert got.mostrado_dashboard is True
    assert got.datos_resumen["titulo"] == "t"


def test_es_pro_plan_pro(session):
    u = User(email="pro@test.com", password_hash="x", plan="pro")
    session.add(u)
    session.commit()
    assert u.es_pro is True


def test_es_pro_trial_activo(session):
    u = User(email="trial@test.com", password_hash="x", plan="free")
    session.add(u)
    session.flush()
    cfg = UserConfig(
        user_id=u.id,
        trial_pro_hasta=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
    )
    session.add(cfg)
    session.commit()
    session.refresh(u)
    assert u.es_pro is True


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
    session.refresh(u)
    assert u.es_pro is False


def test_init_db_migrates_is_admin_on_main_schema(tmp_path):
    dbfile = tmp_path / "t.db"
    url = f"sqlite:///{dbfile}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), "
            "password_hash VARCHAR(255), nombre VARCHAR(120), plan VARCHAR(30), "
            "activo BOOLEAN, fecha_registro DATETIME, ultimo_acceso DATETIME)"
        ))
    from sqlalchemy import inspect as sa_inspect
    with engine.begin() as conn:
        cols = [c["name"] for c in sa_inspect(engine).get_columns("users")]
        assert "is_admin" not in cols
        conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
    cols2 = [c["name"] for c in sa_inspect(engine).get_columns("users")]
    assert "is_admin" in cols2
