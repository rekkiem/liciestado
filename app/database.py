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

# expire_on_commit=False: objetos User siguen usables tras cerrar get_db()
# (crítico para Flask-Login current_user fuera de la sesión)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


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


def _alembic_cfg():
    """Config Alembic apuntando a DATABASE_URL actual."""
    from pathlib import Path
    from alembic.config import Config
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def _alembic_current_rev() -> str | None:
    try:
        from alembic.runtime.migration import MigrationContext
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            return ctx.get_current_revision()
    except Exception as e:
        logger.debug("No se pudo leer revision Alembic: %s", e)
        return None


def _run_sqlite_legacy_migrations() -> None:
    """Solo SQLite: lleva variantes antiguas al estado post–Fase 0."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    _migrate_add_user_id()
    _migrate_add_is_admin()
    _migrate_alerta_schema()
    _migrate_user_config_schema()
    _migrate_api_quota_schema()


def init_db():
    """Inicializa el esquema.

    - PostgreSQL: solo `alembic upgrade head` (sin create_all / PRAGMA).
    - SQLite vacío: create_all + stamp baseline (o upgrade si no hay tablas).
    - SQLite legacy: migraciones _migrate_* → stamp baseline si no hay alembic_version.
    """
    from app import models  # noqa: F401
    from sqlalchemy import inspect, text

    is_sqlite = settings.DATABASE_URL.startswith("sqlite")
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    has_alembic = "alembic_version" in tables
    rev = _alembic_current_rev() if has_alembic else None

    if is_sqlite:
        # Asegura tablas base + columnas legacy
        Base.metadata.create_all(bind=engine)
        _run_sqlite_legacy_migrations()
        if not has_alembic or rev is None:
            try:
                from alembic import command
                command.stamp(_alembic_cfg(), "001_baseline")
                logger.info("init_db: SQLite → alembic stamp 001_baseline")
            except Exception as e:
                logger.warning("init_db: stamp Alembic falló (%s); schema listo vía create_all", e)
        else:
            try:
                from alembic import command
                command.upgrade(_alembic_cfg(), "head")
                logger.info("init_db: SQLite alembic upgrade head (rev previa=%s)", rev)
            except Exception as e:
                logger.warning("init_db: upgrade Alembic: %s", e)
    else:
        # PostgreSQL: solo Alembic
        try:
            from alembic import command
            command.upgrade(_alembic_cfg(), "head")
            logger.info("init_db: PostgreSQL alembic upgrade head")
        except Exception as e:
            logger.error("init_db: fallo alembic en PostgreSQL: %s", e)
            raise

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


def _migrate_api_quota_schema():
    """Alinea api_quota_logs con el ORM (creado_en, limite)."""
    with engine.connect() as conn:
        try:
            result = conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(api_quota_logs)")
            )
            cols = [row[1] for row in result.fetchall()]
            if not cols:
                return  # create_all la crea completa
            if "creado_en" not in cols:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE api_quota_logs ADD COLUMN creado_en DATETIME"
                    )
                )
                conn.execute(
                    __import__("sqlalchemy").text(
                        "UPDATE api_quota_logs SET creado_en = CURRENT_TIMESTAMP "
                        "WHERE creado_en IS NULL"
                    )
                )
                logger.info("Migración: columna api_quota_logs.creado_en añadida")
            if "limite" not in cols:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE api_quota_logs ADD COLUMN limite INTEGER NOT NULL DEFAULT 10000"
                    )
                )
                logger.info("Migración: columna api_quota_logs.limite añadida")
            conn.commit()
        except Exception as e:
            logger.warning("Migración api_quota schema: %s", e)
