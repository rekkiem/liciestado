"""Tests del migrador SQLite → Postgres (Obj2)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sqlite_to_postgres.py"


def test_script_exists():
    assert SCRIPT.is_file()


def test_script_documents_dry_run_and_setval():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--dry-run" in text
    assert "setval" in text
    assert "TABLE_ORDER" in text
    assert "ON CONFLICT" in text


def test_table_order_parents_before_children():
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("TABLE_ORDER = [")
    end = text.index("]", start)
    block = text[start:end]
    assert block.index("users") < block.index("user_tickets")
    assert block.index("users") < block.index("reglas_usuario")
    assert block.index("reglas_usuario") < block.index("alertas_generadas")
    assert block.index("users") < block.index("api_quota_logs")


def test_dry_run_on_empty_sqlite(tmp_path):
    src = tmp_path / "src.db"
    dst = tmp_path / "dst.db"
    conn = sqlite3.connect(src)
    conn.execute(
        "CREATE TABLE licitaciones_snapshot (id INTEGER PRIMARY KEY, codigo TEXT, tipo TEXT, datos TEXT, fecha_sincronizacion TEXT)"
    )
    conn.execute(
        "INSERT INTO licitaciones_snapshot VALUES (1,'C1','licitacion','{}','2026-01-01')"
    )
    conn.commit()
    conn.close()
    conn = sqlite3.connect(dst)
    conn.execute(
        "CREATE TABLE licitaciones_snapshot (id INTEGER PRIMARY KEY, codigo TEXT, tipo TEXT, datos TEXT, fecha_sincronizacion TEXT)"
    )
    conn.commit()
    conn.close()

    import importlib.util

    spec = importlib.util.spec_from_file_location("s2p", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    code = mod.migrate(
        f"sqlite:///{src}",
        f"sqlite:///{dst}",
        dry_run=True,
        batch_size=10,
        skip_existing=False,
        tables=["licitaciones_snapshot"],
    )
    assert code == 0
