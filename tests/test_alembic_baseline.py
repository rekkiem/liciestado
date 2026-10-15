"""Smoke tests Alembic baseline (Obj2)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_alembic_ini_exists():
    assert (ROOT / "alembic.ini").is_file()


def test_baseline_revision_file_exists():
    versions = list((ROOT / "alembic" / "versions").glob("*.py"))
    assert any("001_baseline" in p.name for p in versions)


def test_env_py_imports_settings():
    text = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "settings.DATABASE_URL" in text
    assert "target_metadata" in text
