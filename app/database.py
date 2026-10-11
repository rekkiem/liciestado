"""app/database.py — SQLAlchemy engine, session y migraciones SQLite-safe."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import settings

logger = logging.getLogger(__name__)

# SQLite necesita check_same_thread=False para multi-thread (scheduler + Flask)
_connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    if settings.DATABASE_URL.startswith("sqlite"):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    from app import models  # noqa
    Base.metadata.create_all(bind=engine)
    _migrate_add_user_id()
    _migrate_add_is_admin()
    _migrate_alerta_schema()
    _migrate_user_config_schema()
    logger.info("Base de datos inicializada correctamente.")


def _migrate_add_user_id():
    """Añade user_id a tablas legacy si no existe.
    Compatible con SQLite (no soporta ALTER TABLE ADD COLUMN IF NOT EXISTS en versiones viejas).
    """
    from sqlalchemy import text
    tablas = ("reglas_usuario", "alertas_generadas")
    with engine.connect() as conn:
        for tabla in tablas:
            try:
                result = conn.execute(text(f"PRAGMA table_info({tabla})"))
                cols = [row[1] for row in result.fetchall()]
                if cols and "user_id" not in cols:
                    conn.execute(text(f"ALTER TABLE {tabla} ADD COLUMN user_id INTEGER"))
                    conn.commit()
                    logger.info("Migración: columna %s.user_id añadida", tabla)
            except Exception as e:
                logger.warning("Migración user_id %s: %s", tabla, e)


def _migrate_add_is_admin():
    """Añade columna is_admin a users si no existe (SQLite-safe)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            result = conn.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in result.fetchall()]
            if cols and "is_admin" not in cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
                )
                conn.commit()
                logger.info("Migración: columna users.is_admin añadida")
        except Exception as e:
            logger.warning("Migración is_admin: %s", e)


def _migrate_alerta_schema():
    """Alinea alertas_generadas: añade columnas faltantes para BDs antiguas y de main.

    - mostrado_dashboard (default 1)
    - tipo_entidad (NOT NULL DEFAULT 'licitacion') — requerido por el ORM actual;
      BDs creadas con esquema main sin esta columna fallan al consultar sin el ALTER.
    """
    with engine.connect() as conn:
        try:
            result = conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(alertas_generadas)")
            )
            cols = [row[1] for row in result.fetchall()]
            if not cols:
                return  # tabla aún no existe; create_all la crea completa
            if "mostrado_dashboard" not in cols:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE alertas_generadas ADD COLUMN mostrado_dashboard BOOLEAN DEFAULT 1"
                    )
                )
                logger.info("Migración: columna alertas_generadas.mostrado_dashboard añadida")
            if "tipo_entidad" not in cols:
                # SQLite permite ADD COLUMN NOT NULL solo con DEFAULT
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE alertas_generadas ADD COLUMN tipo_entidad VARCHAR(50) NOT NULL DEFAULT 'licitacion'"
                    )
                )
                logger.info("Migración: columna alertas_generadas.tipo_entidad añadida")
            conn.commit()
        except Exception as e:
            logger.warning("Migración alerta schema: %s", e)


def _migrate_user_config_schema():
    """Añade columnas faltantes en user_configs (p.ej. digest_hora tras restore desde main)."""
    with engine.connect() as conn:
        try:
            result = conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(user_configs)")
            )
            cols = [row[1] for row in result.fetchall()]
            if not cols:
                return  # tabla aún no existe; create_all la crea completa
            adds = []
            if "digest_hora" not in cols:
                adds.append(("digest_hora", "INTEGER DEFAULT 8"))
            if "notif_dashboard" not in cols:
                adds.append(("notif_dashboard", "BOOLEAN DEFAULT 1"))
            if "trial_pro_hasta" not in cols:
                adds.append(("trial_pro_hasta", "DATETIME"))
            if "webhook_url" not in cols:
                adds.append(("webhook_url", "VARCHAR(512)"))
            if "webhook_activo" not in cols:
                adds.append(("webhook_activo", "BOOLEAN DEFAULT 0"))
            if "notif_mode" not in cols:
                adds.append(("notif_mode", "VARCHAR(20) DEFAULT 'digest'"))
            for name, typedef in adds:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE user_configs ADD COLUMN {name} {typedef}"
                    )
                )
                logger.info("Migración: columna user_configs.%s añadida", name)
            if adds:
                conn.commit()
        except Exception as e:
            logger.warning("Migración user_config schema: %s", e)
