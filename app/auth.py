"""
app/auth.py — Lógica de autenticación y gestión de usuarios.

Funciones:
  registrar_usuario()    → crea usuario nuevo con password hasheada
  verificar_password()   → login
  guardar_ticket()       → cifra y persiste ticket MP por usuario
  validar_ticket_api()   → prueba el ticket contra la API real
  loader_usuario()       → para Flask-Login
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import bcrypt

from app.database import get_db
from app.models import User, UserTicket
from app.crypto import cifrar_ticket, descifrar_ticket

logger = logging.getLogger(__name__)


# ── Password ──────────────────────────────────────────────────────────────────

def hashear_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verificar_password(password: str, hash_almacenado: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hash_almacenado.encode())
    except Exception:
        return False


# ── Registro ──────────────────────────────────────────────────────────────────

class EmailYaRegistrado(Exception):
    pass


class PasswordDebil(Exception):
    pass


def registrar_usuario(email: str, password: str, nombre: str = "") -> User:
    """
    Crea un usuario nuevo. expire_on_commit=False garantiza acceso post-sesión.
    Raises: EmailYaRegistrado, PasswordDebil
    """
    email = email.strip().lower()
    if len(password) < 8:
        raise PasswordDebil("La contraseña debe tener al menos 8 caracteres.")
    with get_db() as db:
        existe = db.query(User).filter_by(email=email).first()
        if existe:
            raise EmailYaRegistrado(f"El email {email} ya está registrado.")
        user = User(
            email=email, password_hash=hashear_password(password),
            nombre=nombre.strip() or email.split("@")[0], plan="free",
        )
        db.add(user)
        db.flush()
        return user   # expire_on_commit=False → seguro fuera de sesión


# ── Login ─────────────────────────────────────────────────────────────────────

def autenticar_usuario(email: str, password: str) -> Optional[User]:
    """
    Verifica credenciales. Con expire_on_commit=False el objeto User
    queda accesible después de cerrar la sesión (requerido por Flask-Login).
    """
    email = email.strip().lower()
    with get_db() as db:
        user = db.query(User).filter_by(email=email, activo=True).first()
        if not user:
            return None
        if not verificar_password(password, user.password_hash):
            return None
        user.ultimo_acceso = datetime.now(timezone.utc).replace(tzinfo=None)
        return user   # expire_on_commit=False → seguro fuera de la sesión


# ── Ticket ────────────────────────────────────────────────────────────────────

def guardar_ticket(user_id: int, ticket_plano: str) -> UserTicket:
    """
    Cifra y guarda el ticket de Mercado Público para el usuario.
    Desactiva tickets anteriores.
    """
    cifrado = cifrar_ticket(ticket_plano.strip())
    with get_db() as db:
        # Desactivar tickets anteriores
        db.query(UserTicket).filter_by(user_id=user_id, activo=True).update({"activo": False})
        nuevo = UserTicket(user_id=user_id, ticket_cifrado=cifrado, activo=True)
        db.add(nuevo)
        db.flush()
        ticket_id = nuevo.id

    logger.info("Ticket guardado para user_id=%d", user_id)
    with get_db() as db:
        return db.query(UserTicket).filter_by(id=ticket_id).first()


def obtener_ticket_plano(user_id: int) -> Optional[str]:
    """Obtiene y descifra el ticket activo del usuario. None si no tiene."""
    with get_db() as db:
        ut = db.query(UserTicket).filter_by(user_id=user_id, activo=True).first()
        if not ut:
            return None
        return descifrar_ticket(ut.ticket_cifrado)


def validar_ticket_api(ticket: str) -> tuple[bool, str]:
    """
    Valida el ticket haciendo una petición real a la API de Mercado Público.
    Retorna (True, "OK") o (False, "mensaje de error").
    """
    import requests as req
    try:
        r = req.get(
            "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json",
            params={"ticket": ticket, "fecha": "01012024", "pagina": 1},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            if "Listado" in data or "Cantidad" in data:
                return True, "Ticket válido"
            return False, "La API respondió pero el formato es inesperado"
        elif r.status_code == 401:
            return False, "Ticket inválido o expirado (401)"
        elif r.status_code == 400:
            return False, "Ticket rechazado por la API (400)"
        else:
            return False, f"Error HTTP {r.status_code} de la API"
    except req.exceptions.Timeout:
        return False, "La API de Mercado Público no responde (timeout)"
    except Exception as e:
        return False, f"Error de conexión: {e}"


# ── Flask-Login loader ────────────────────────────────────────────────────────

def cargar_usuario(user_id: str) -> Optional[User]:
    """Cargador para Flask-Login."""
    try:
        uid = int(user_id)
    except (ValueError, TypeError):
        return None
    with get_db() as db:
        return db.query(User).filter_by(id=uid, activo=True).first()


# ── Cambio de contraseña ──────────────────────────────────────────────────────

def cambiar_password(user_id: int, password_actual: str, password_nuevo: str) -> tuple[bool, str]:
    with get_db() as db:
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            return False, "Usuario no encontrado"
        if not verificar_password(password_actual, user.password_hash):
            return False, "Contraseña actual incorrecta"
        if len(password_nuevo) < 8:
            return False, "La nueva contraseña debe tener al menos 8 caracteres"
        user.password_hash = hashear_password(password_nuevo)
    return True, "Contraseña actualizada correctamente"
