"""Tests for app.crypto — F2 regression."""
import os
import pytest
from cryptography.fernet import Fernet


def test_roundtrip_with_generated_key(monkeypatch):
    monkeypatch.delenv("FERNET_KEY", raising=False)
    # Force re-import with clean state
    import importlib
    import app.crypto as crypto
    importlib.reload(crypto)
    plain = "ticket-secreto-123"
    enc = crypto.cifrar(plain)
    assert enc != plain
    assert crypto.descifrar(enc) == plain


def test_roundtrip_with_env_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    import importlib
    import app.crypto as crypto
    importlib.reload(crypto)
    plain = "CA11674E-test"
    assert crypto.descifrar(crypto.cifrar(plain)) == plain


def test_invalid_token_raises(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    import importlib
    import app.crypto as crypto
    importlib.reload(crypto)
    with pytest.raises(ValueError):
        crypto.descifrar("not-a-valid-token")
