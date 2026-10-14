"""Tests dialect helpers + contrato analytics (Obj2).

json_as_text debe devolver texto sin comillas JSON extra.
date_trunc_expr debe devolver YYYY-MM / YYYY-MM-DD.
"""
from __future__ import annotations

from app.db_dialect import date_trunc_expr, is_postgres, json_as_text


def test_is_postgres_detects_url():
    assert is_postgres("postgresql://u:p@localhost/db") is True
    assert is_postgres("postgres://u:p@localhost/db") is True
    assert is_postgres("sqlite:///./x.db") is False


def test_json_as_text_callable():
    # Solo valida que el helper construye expresión (sin ejecutar SQL aún)
    from app.models import LicitacionSnapshot
    expr = json_as_text(LicitacionSnapshot.datos, "organismo")
    assert expr is not None


def test_date_trunc_expr_month_day():
    from app.models import LicitacionSnapshot
    m = date_trunc_expr(LicitacionSnapshot.fecha_publicacion, "month")
    d = date_trunc_expr(LicitacionSnapshot.fecha_sincronizacion, "day")
    assert m is not None and d is not None
