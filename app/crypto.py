"""
app/crypto.py — Cifrado simétrico con Fernet para secretos por usuario.

La clave maestra viene de FERNET_KEY (vía config/settings → .env).
Debe ser el string url-safe base64 de 44 caracteres que genera Fernet.generate_key().decode().

Comportamiento:
  - Producción (APP_ENV=production o DATABASE_URL postgres*): sin clave válida → no arranca.
  - Desarrollo: clave temporal con aviso fuerte; no se debe persistir tickets con ella
    sin haber fijado FERNET_KEY (ver cifrar_ticket).
"""
from __future__ import annotations

import logging
import os
import sys

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# True si la clave en uso fue generada en memoria (no persistida en .env)
_EPHEMERAL_KEY = False


def _is_production_like() -> bool:
    app_env = (os.environ.get("APP_ENV") or "").strip().lower()
    if app_env in {"production", "prod", "staging"}:
        return True
    try:
        from config import settings

        env = (getattr(settings, "APP_ENV", None) or "").strip().lower()
        if env in {"production", "prod", "staging"}:
            return True
        db = (settings.DATABASE_URL or "").lower()
        if db.startswith("postgresql") or db.startswith("postgres"):
            return True
    except Exception:
        db = (os.environ.get("DATABASE_URL") or "").lower()
        if db.startswith("postgresql") or db.startswith("postgres"):
            return True
    return False


def _resolve_fernet_key_raw() -> str:
    """Prioridad: settings (pydantic lee .env) → os.environ."""
    try:
        from config import settings

        raw = (settings.FERNET_KEY or "").strip()
        if raw:
            return raw
    except Exception as e:
        logger.debug("settings.FERNET_KEY no disponible: %s", e)
    return (os.environ.get("FERNET_KEY") or "").strip()


def _validate_key_bytes(raw: str) -> bytes:
    key_bytes = raw.encode("ascii")
    Fernet(key_bytes)  # raises if invalid
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
    """True si la clave actual no proviene de FERNET_KEY persistida."""
    return _EPHEMERAL_KEY


def cifrar(texto: str) -> str:
    """Cifra un string y retorna el token como string base64-url."""
    return _fernet.encrypt(texto.encode("utf-8")).decode("ascii")


def descifrar(token: str) -> str:
    """Descifra un token. Lanza ValueError si el token es inválido."""
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Token de cifrado inválido o clave incorrecta") from e


def cifrar_ticket(texto: str) -> str:
    """
    Cifra ticket. En desarrollo, si la clave es efímera, avisa fuerte
    (el ticket no sobrevivirá un reinicio).
    """
    if _EPHEMERAL_KEY:
        logger.error(
            "Guardando ticket con FERNET_KEY temporal: se perderá al reiniciar. "
            "Fija FERNET_KEY en .env (python scripts/generar_fernet_key.py)."
        )
    return cifrar(texto)


descifrar_ticket = descifrar
