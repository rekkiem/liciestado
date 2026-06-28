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
                # SQLite: obtener columnas existentes
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
