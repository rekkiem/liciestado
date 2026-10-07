"""
app/crypto.py — Cifrado simétrico con Fernet para secretos por usuario.

Uso:
    cifrar_ticket("mi_ticket_real")   → str cifrado para guardar en BD
    descifrar_ticket("str_cifrado")   → ticket original

La clave maestra viene de FERNET_KEY (env var).
Debe ser el string url-safe base64 de 44 caracteres que genera Fernet.generate_key().decode().
Si no existe, se genera una nueva y se avisa al operador para que la persista en .env.
ADVERTENCIA: si se pierde la clave, los tickets cifrados son irrecuperables.
"""
from __future__ import annotations
import os
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_or_create_key() -> bytes:
    """
    Obtiene la clave Fernet desde FERNET_KEY (string url-safe base64).
    Fernet() espera exactamente los bytes del string generado por Fernet.generate_key().
    No hay que decodificar base64 a mano: el constructor de Fernet lo valida.
    """
    raw = os.environ.get("FERNET_KEY", "").strip()
    if raw:
        try:
            # Fernet acepta el string url-safe base64 (44 chars) como bytes
            key_bytes = raw.encode("ascii")
            # Validar que sea una clave Fernet válida
            Fernet(key_bytes)
            return key_bytes
        except Exception as e:
            logger.error("FERNET_KEY inválida (%s). Generando una temporal.", e)

    # Generar clave nueva
    key = Fernet.generate_key()  # already url-safe base64 bytes
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
