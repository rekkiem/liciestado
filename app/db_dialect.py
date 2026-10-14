"""Helpers SQL dialect-safe (SQLite + PostgreSQL).

Usados por analytics, routes y bid_analyzer para evitar:
- cast(JSON, String) que en PG añade comillas
- func.strftime (solo SQLite)
"""
from __future__ import annotations

from sqlalchemy import String, cast, func
from sqlalchemy.engine import Engine
from sqlalchemy.sql.elements import ColumnElement

from config import settings


def is_postgres(url: str | None = None) -> bool:
    u = (url or settings.DATABASE_URL or "").lower()
    return u.startswith("postgresql") or u.startswith("postgres")


def json_as_text(json_col, key: str) -> ColumnElement:
    """Extrae texto de un campo JSON sin comillas extra.

    SQLite / SQLAlchemy JSON: path access + as_string cuando existe.
    PostgreSQL: operador ->> vía .as_string().
    """
    elem = json_col[key]
    # SQLAlchemy 2 JSON path element
    if hasattr(elem, "as_string"):
        return elem.as_string()
    # Fallback legado
    return cast(elem, String)


def date_trunc_expr(column, grain: str) -> ColumnElement:
    """Formato estable YYYY-MM o YYYY-MM-DD en ambos motores."""
    grain = grain.lower()
    if is_postgres():
        if grain in ("month", "yyyy-mm", "ym"):
            return func.to_char(column, "YYYY-MM")
        if grain in ("day", "yyyy-mm-dd", "ymd"):
            return func.to_char(column, "YYYY-MM-DD")
        return func.to_char(column, "YYYY-MM-DD")
    # SQLite
    if grain in ("month", "yyyy-mm", "ym"):
        return func.strftime("%Y-%m", column)
    if grain in ("day", "yyyy-mm-dd", "ymd"):
        return func.strftime("%Y-%m-%d", column)
    return func.strftime("%Y-%m-%d", column)
