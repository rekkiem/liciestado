"""Verifica que analytics/routes usan helpers dialect-safe (Obj2)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_analytics_no_raw_cast_or_strftime():
    text = (ROOT / "app" / "analytics.py").read_text(encoding="utf-8")
    assert "json_as_text" in text
    assert "date_trunc_expr" in text
    assert "func.strftime" not in text
    assert "cast(LicitacionSnapshot.datos" not in text


def test_routes_use_json_as_text_for_json_fields():
    text = (ROOT / "app" / "dashboard" / "routes.py").read_text(encoding="utf-8")
    assert "json_as_text" in text
    assert "cast(LicitacionSnapshot.datos" not in text
    assert "cast(AlertaGenerada.datos_resumen" not in text


def test_bid_analyzer_uses_json_as_text():
    text = (ROOT / "app" / "bid_analyzer.py").read_text(encoding="utf-8")
    assert "json_as_text" in text
    assert "cast(LicitacionSnapshot.datos" not in text
