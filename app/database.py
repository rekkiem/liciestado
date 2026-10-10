"""
app/database.py — Motor SQLAlchemy + Flask-Login init.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from contextlib import contextmanager
import logging

from config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    pool_pre_ping=True,
    echo=False,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if "sqlite" in settings.DATABASE_URL:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


@contextmanager
def get_db() -> Session:
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
    """
    Migración no destructiva: añade columna user_id a tablas existentes
    si no existe. Compatible con SQLite (no soporta ALTER TABLE ADD COLUMN
    con FK, pero sí con NULL).
    """
    with engine.connect() as conn:
        for tabla, col in [
            ("reglas_usuario",   "user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"),
            ("alertas_generadas","user_id INTEGER REFERENCES users(id) ON DELETE CASCADE"),
        ]:
            try:
                result = conn.execute(
                    __import__("sqlalchemy").text(f"PRAGMA table_info({tabla})")
                )
                cols = [row[1] for row in result.fetchall()]
                if "user_id" not in cols:
                    conn.execute(
                        __import__("sqlalchemy").text(
                            f"ALTER TABLE {tabla} ADD COLUMN user_id INTEGER"
                        )
                    )
                    conn.commit()
                    logger.info("Migración: columna user_id añadida a %s", tabla)
            except Exception as e:
                logger.debug("Migración %s: %s", tabla, e)


def _migrate_add_is_admin():
    """Añade columna is_admin a users si no existe (SQLite-safe)."""
    with engine.connect() as conn:
        try:
            result = conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(users)")
            )
            cols = [row[1] for row in result.fetchall()]
            if "is_admin" not in cols:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"
                    )
                )
                conn.commit()
                logger.info("Migración: columna users.is_admin añadida")
        except Exception as e:
            logger.warning("Migración is_admin: %s", e)


def _migrate_alerta_schema():
    """Alinea alertas_generadas al schema de main: añade mostrado_dashboard si falta.
    SQLite no puede DROP COLUMN fácilmente; tipo_entidad residual se ignora en el ORM.
    """
    with engine.connect() as conn:
        try:
            result = conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(alertas_generadas)")
            )
            cols = [row[1] for row in result.fetchall()]
            if "mostrado_dashboard" not in cols:
                conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE alertas_generadas ADD COLUMN mostrado_dashboard BOOLEAN DEFAULT 1"
                    )
                )
                conn.commit()
                logger.info("Migración: columna alertas_generadas.mostrado_dashboard añadida")
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
