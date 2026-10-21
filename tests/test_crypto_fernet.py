"""FERNET_KEY: válida, ausente en producción, inválida."""
from __future__ import annotations

import importlib
import os
import sys

import pytest
from cryptography.fernet import Fernet


def _reload_crypto(monkeypatch, *, fernet_key: str, app_env: str, database_url: str):
    monkeypatch.setenv("FERNET_KEY", fernet_key)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", database_url)
    for mod in ("config", "app.crypto"):
        if mod in sys.modules:
            del sys.modules[mod]
    import config  # noqa: F401
    importlib.reload(sys.modules.get("config") or importlib.import_module("config"))
    crypto = importlib.import_module("app.crypto")
    return importlib.reload(crypto)


def test_fernet_valid_key_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    crypto = _reload_crypto(
        monkeypatch, fernet_key=key, app_env="development", database_url="sqlite://"
    )
    assert crypto.is_ephemeral_key() is False
    token = crypto.cifrar_ticket("ticket-abc")
    assert crypto.descifrar_ticket(token) == "ticket-abc"


def test_fernet_missing_in_production_exits(monkeypatch):
    with pytest.raises(SystemExit) as ei:
        _reload_crypto(
            monkeypatch,
            fernet_key="",
            app_env="production",
            database_url="sqlite://",
        )
    assert "FERNET_KEY" in str(ei.value)


def test_fernet_invalid_in_production_exits(monkeypatch):
    with pytest.raises(SystemExit) as ei:
        _reload_crypto(
            monkeypatch,
            fernet_key="not-a-valid-fernet-key!!!!",
            app_env="production",
            database_url="sqlite://",
        )
    assert "FERNET_KEY" in str(ei.value) or "inválida" in str(ei.value).lower() or "invalid" in str(ei.value).lower()


def test_fernet_missing_in_dev_allows_ephemeral(monkeypatch):
    crypto = _reload_crypto(
        monkeypatch, fernet_key="", app_env="development", database_url="sqlite://"
    )
    assert crypto.is_ephemeral_key() is True
    token = crypto.cifrar("hello")
    assert crypto.descifrar(token) == "hello"


def test_fernet_postgres_url_treated_as_production(monkeypatch):
    with pytest.raises(SystemExit):
        _reload_crypto(
            monkeypatch,
            fernet_key="",
            app_env="development",
            database_url="postgresql+psycopg://u:p@localhost:5432/db",
        )
