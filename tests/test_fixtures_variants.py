"""Carga de fixtures de las 3 variantes de BD (Objetivo 2).

Por ahora solo verifica que el SQL de fixture es cargable en SQLite.
Cuando exista Alembic, cada test subirá a head y comprobará datos intactos.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    "name,min_rows",
    [
        ("variant1_pre_multitenant.sql", 2),
        ("variant2_partial_userid.sql", 1),
        ("variant3_post_fase0.sql", 3),
    ],
)
def test_fixture_loads_in_sqlite(name: str, min_rows: int, tmp_path: Path):
    sql = (FIXTURES / name).read_text(encoding="utf-8")
    dbfile = tmp_path / "t.db"
    conn = sqlite3.connect(dbfile)
    try:
        conn.executescript(sql)
        n = conn.execute("SELECT COUNT(*) FROM licitaciones_snapshot").fetchone()[0]
        assert n >= min_rows
    finally:
        conn.close()


def test_variant1_has_no_user_id_column(tmp_path: Path):
    sql = (FIXTURES / "variant1_pre_multitenant.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(tmp_path / "v1.db")
    conn.executescript(sql)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(reglas_usuario)").fetchall()]
    assert "user_id" not in cols
    conn.close()


def test_variant3_has_tipo_entidad_and_quota(tmp_path: Path):
    sql = (FIXTURES / "variant3_post_fase0.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(tmp_path / "v3.db")
    conn.executescript(sql)
    cols_a = [r[1] for r in conn.execute("PRAGMA table_info(alertas_generadas)").fetchall()]
    cols_q = [r[1] for r in conn.execute("PRAGMA table_info(api_quota_logs)").fetchall()]
    assert "tipo_entidad" in cols_a
    assert "limite" in cols_q and "creado_en" in cols_q
    conn.close()
