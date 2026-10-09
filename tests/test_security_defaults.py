"""C5: check_insecure_defaults warns in dev, raises in production."""
import pytest
from app.security import check_insecure_defaults


def test_insecure_defaults_warns_in_dev(monkeypatch):
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    import config
    monkeypatch.setattr(config.settings, "SECRET_KEY", "cambia-esto-en-produccion")
    monkeypatch.setattr(config.settings, "DASHBOARD_PASS", "admin")
    check_insecure_defaults()  # should not raise


def test_insecure_defaults_raises_in_production(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    import config
    monkeypatch.setattr(config.settings, "SECRET_KEY", "cambia-esto-en-produccion")
    monkeypatch.setattr(config.settings, "DASHBOARD_PASS", "admin")
    with pytest.raises(RuntimeError):
        check_insecure_defaults()
