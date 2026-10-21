"""
app/crypto.py — Cifrado simétrico con Fernet para secretos por usuario.

Uso:
    cifrar_ticket("mi_ticket_real")   → str cifrado para guardar en BD
    descifrar_ticket("str_cifrado")   → ticket original

La clave maestra viene de FERNET_KEY (vía config/settings → .env).
Debe ser el string url-safe base64 de 44 caracteres que genera Fernet.generate_key().decode().
Si no existe, se genera una nueva y se avisa al operador para que la persista en .env.
ADVERTENCIA: si se pierde la clave, los tickets cifrados son irrecuperables.
"""
from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


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


def _get_or_create_key() -> bytes:
    """
    Obtiene la clave Fernet desde FERNET_KEY (string url-safe base64).
    Fernet() espera exactamente los bytes del string generado por Fernet.generate_key().
    """
    raw = _resolve_fernet_key_raw()
    if raw:
        try:
            key_bytes = raw.encode("ascii")
            Fernet(key_bytes)  # validar
            return key_bytes
        except Exception as e:
            logger.error("FERNET_KEY inválida (%s). Generando una temporal.", e)

    key = Fernet.generate_key()
    logger.warning(
        "\n"
        "══════════════════════════════════════════════════════════\n"
        "  FERNET_KEY no encontrada o inválida en .env — generando nueva clave.\n"
        "  Agrega esta línea a tu .env y NO la pierdas:\n"
        "  FERNET_KEY=%s\n"
        "══════════════════════════════════════════════════════════",
        key.decode(),
    )
    return key


_fernet = Fernet(_get_or_create_key())


def cifrar(texto: str) -> str:
    """Cifra un string y retorna el token como string base64-url."""
    return _fernet.encrypt(texto.encode("utf-8")).decode("ascii")


def descifrar(token: str) -> str:
    """Descifra un token. Lanza ValueError si el token es inválido."""
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Token de cifrado inválido o clave incorrecta") from e


# Aliases semánticos para tickets
cifrar_ticket = cifrar
descifrar_ticket = descifrar
