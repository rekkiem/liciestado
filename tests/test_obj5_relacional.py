"""Obj5: RUT, hash, backfill extract + upsert."""
from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-32-chars-long")
os.environ["API_QUOTA_PERSIST"] = "0"

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


def test_normalizar_rut():
    from app.rut import normalizar_rut, rut_display

    assert normalizar_rut("12.345.678-9") == "123456789"
    assert normalizar_rut("12345678-k") == "12345678K"
    assert normalizar_rut("") is None
    assert normalizar_rut(None) is None
    assert rut_display("123456789") == "12345678-9"


def test_content_hash_stable():
    from app.relacional import content_hash

    a = {"codigo": "X-1", "titulo": "T", "monto_clp": 10, "_raw": {"Items": []}}
    b = {"codigo": "X-1", "titulo": "T", "monto_clp": 10, "_raw": {"Items": []}}
    c = {"codigo": "X-1", "titulo": "T2", "monto_clp": 10, "_raw": {"Items": []}}
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) != content_hash(c)


def test_extract_and_upsert(db_bind):
    from datetime import datetime, timezone
    from app.database import get_db
    from app.models import Licitacion, LicitacionSnapshot, LicitacionVersion, Proveedor
    from app.relacional import upsert_snapshot_relacional

    datos = {
        "tipo": "licitacion",
        "codigo": "L1-1234-2024",
        "titulo": "Servicio TI",
        "estado": "Adjudicada",
        "organismo": "MINISTERIO X",
        "codigo_organismo": "ORG-1",
        "region": 13,
        "monto_clp": 1_000_000,
        "_raw": {
            "CodigoExterno": "L1-1234-2024",
            "Nombre": "Servicio TI",
            "Comprador": {"CodigoOrganismo": "ORG-1", "NombreOrganismo": "MINISTERIO X"},
            "Items": {
                "Listado": [
                    {
                        "CodigoProducto": "P1",
                        "Descripcion": "Item uno",
                        "Cantidad": 2,
                        "Adjudicacion": {
                            "RutProveedor": "76.123.456-0",
                            "NombreProveedor": "Proveedor SA",
                            "MontoUnitario": 500000,
                        },
                    }
                ]
            },
        },
    }

    with get_db() as db:
        snap = LicitacionSnapshot(
            codigo="L1-1234-2024",
            tipo="licitacion",
            datos=datos,
            estado="Adjudicada",
            region=13,
            monto_clp=1_000_000,
            fecha_sincronizacion=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(snap)
        db.flush()
        st = upsert_snapshot_relacional(db, snap, dry_run=False)
        assert st == "new"
        st2 = upsert_snapshot_relacional(db, snap, dry_run=False)
        assert st2 == "unchanged"

        lic = db.query(Licitacion).filter_by(codigo="L1-1234-2024").one()
        assert lic.content_hash
        assert db.query(LicitacionVersion).filter_by(licitacion_id=lic.id).count() == 1
        prov = db.query(Proveedor).filter_by(rut="761234560").one()
        assert "Proveedor" in (prov.nombre or "")


def test_hash_change_creates_version(db_bind):
    from datetime import datetime, timezone
    from app.database import get_db
    from app.models import Licitacion, LicitacionSnapshot, LicitacionVersion
    from app.relacional import upsert_snapshot_relacional

    base = {
        "codigo": "L2-1",
        "titulo": "A",
        "codigo_organismo": "O2",
        "organismo": "Org2",
        "_raw": {"CodigoExterno": "L2-1", "Nombre": "A", "Items": {"Listado": []}},
    }
    with get_db() as db:
        snap = LicitacionSnapshot(
            codigo="L2-1",
            tipo="licitacion",
            datos=base,
            fecha_sincronizacion=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(snap)
        db.flush()
        upsert_snapshot_relacional(db, snap, dry_run=False)
        base2 = dict(base)
        base2["titulo"] = "B"
        base2["_raw"] = dict(base["_raw"])
        base2["_raw"]["Nombre"] = "B"
        snap.datos = base2
        st = upsert_snapshot_relacional(db, snap, dry_run=False)
        assert st == "updated"
        lic = db.query(Licitacion).filter_by(codigo="L2-1").one()
        assert db.query(LicitacionVersion).filter_by(licitacion_id=lic.id).count() == 2
