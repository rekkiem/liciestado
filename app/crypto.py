"""
app/crypto.py — Cifrado simétrico con Fernet para secretos por usuario.

La clave maestra viene de FERNET_KEY (vía env / config → .env).
Debe ser el string url-safe base64 de 44 caracteres que genera Fernet.generate_key().decode().

Comportamiento:
  - Producción (APP_ENV=production|staging o DATABASE_URL postgres*): sin clave válida → no arranca.
  - Desarrollo: clave temporal con aviso fuerte.
"""
from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_EPHEMERAL_KEY = False


def _env_first(*names: str) -> str:
    """Lee os.environ primero (tests/monkeypatch), luego settings."""
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    try:
        from config import settings

        for name in names:
            raw = (getattr(settings, name, None) or "").strip()
            if raw:
                return raw
    except Exception as e:
        logger.debug("settings no disponible: %s", e)
    return ""


def _is_production_like() -> bool:
    app_env = _env_first("APP_ENV").lower()
    if app_env in {"production", "prod", "staging"}:
        return True
    db = _env_first("DATABASE_URL").lower()
    return db.startswith("postgresql") or db.startswith("postgres")


def _sanitize_fernet_raw(raw: str) -> str:
    """Descarta placeholders y valores no-ASCII (p.ej. el carácter … pegado por error)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw in {"…", "...", "CHANGEME", "changeme", "your-key-here", "<FERNET_KEY>"}:
        return ""
    try:
        raw.encode("ascii")
    except UnicodeEncodeError:
        logger.warning("FERNET_KEY contiene caracteres no-ASCII; se ignora.")
        return ""
    return raw


def _resolve_fernet_key_raw() -> str:
    return _sanitize_fernet_raw(_env_first("FERNET_KEY"))


def _validate_key_bytes(raw: str) -> bytes:
    key_bytes = raw.encode("ascii")
    Fernet(key_bytes)
    return key_bytes


def _get_or_create_key() -> bytes:
    global _EPHEMERAL_KEY
    raw = _resolve_fernet_key_raw()
    if raw:
        try:
            key_bytes = _validate_key_bytes(raw)
            _EPHEMERAL_KEY = False
            return key_bytes
        except Exception as e:
            msg = (
                f"FERNET_KEY inválida ({e}). "
                "Genera una con: python scripts/generar_fernet_key.py"
            )
            if _is_production_like():
                logger.critical(msg)
                raise SystemExit(f"FATAL: {msg}") from e
            logger.error("%s Generando clave temporal (solo desarrollo).", msg)

    msg_missing = (
        "FERNET_KEY no encontrada o vacía. "
        "Genera una con: python scripts/generar_fernet_key.py y fíjala en .env"
    )
    if _is_production_like():
        logger.critical(msg_missing)
        raise SystemExit(f"FATAL: {msg_missing}")

    key = Fernet.generate_key()
    _EPHEMERAL_KEY = True
    logger.warning(
        "\n"
        "══════════════════════════════════════════════════════════\n"
        "  FERNET_KEY ausente — clave TEMPORAL de desarrollo.\n"
        "  Los tickets cifrados con esta clave se perderán al reiniciar.\n"
        "  Fija una clave estable:\n"
        "    python scripts/generar_fernet_key.py\n"
        "    # pega FERNET_KEY=... en .env\n"
        "  Clave temporal de esta sesión:\n"
        "  FERNET_KEY=%s\n"
        "══════════════════════════════════════════════════════════",
        key.decode(),
    )
    return key


_fernet = Fernet(_get_or_create_key())


def is_ephemeral_key() -> bool:
    return _EPHEMERAL_KEY


def cifrar(texto: str) -> str:
    return _fernet.encrypt(texto.encode("utf-8")).decode("ascii")


def descifrar(token: str) -> str:
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Token de cifrado inválido o clave incorrecta") from e


def cifrar_ticket(texto: str) -> str:
    if _EPHEMERAL_KEY:
        logger.error(
            "Guardando ticket con FERNET_KEY temporal: se perderá al reiniciar. "
            "Fija FERNET_KEY en .env (python scripts/generar_fernet_key.py)."
        )
    return cifrar(texto)


descifrar_ticket = descifrar
