"""
app/crypto.py — Cifrado simétrico con Fernet para secretos por usuario.

Uso:
    cifrar_ticket("mi_ticket_real")   → str cifrado para guardar en BD
    descifrar_ticket("str_cifrado")   → ticket original

La clave maestra viene de FERNET_KEY (env var).
Si no existe, se genera una y se avisa al operador para que la persista en .env
"""
import os
import base64
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# ── Clave maestra ─────────────────────────────────────────────────────────────

def _get_or_create_key() -> bytes:
    """
    Obtiene la clave Fernet desde FERNET_KEY.
    Si no existe, genera una nueva y la imprime para que se guarde en .env
    ADVERTENCIA: si se pierde la clave, los tickets cifrados son irrecuperables.
    """
    raw = os.environ.get("FERNET_KEY", "")
    if raw:
        try:
            return base64.urlsafe_b64decode(raw.encode())
        except Exception:
            pass

    # Generar clave nueva
    key = Fernet.generate_key()
    logger.warning(
        "\n"
        "══════════════════════════════════════════════════════════\n"
        "  FERNET_KEY no encontrada en .env — generando nueva clave.\n"
        "  Agrega esta línea a tu .env y NO la pierdas:\n"
        "  FERNET_KEY=%s\n"
        "══════════════════════════════════════════════════════════",
        key.decode(),
    )
    return key


_fernet = Fernet(_get_or_create_key())


# ── API pública ───────────────────────────────────────────────────────────────

def cifrar(texto: str) -> str:
    """Cifra un string y retorna el token como string base64-url."""
    return _fernet.encrypt(texto.encode()).decode()


def descifrar(token: str) -> str:
    """Descifra un token. Lanza ValueError si el token es inválido."""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("Token de cifrado inválido o clave incorrecta") from e


# Aliases semánticos para tickets
cifrar_ticket   = cifrar
descifrar_ticket = descifrar
