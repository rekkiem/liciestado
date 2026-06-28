"""
app/models.py — Modelos ORM multi-tenant.

Tablas nuevas:
  users           → usuarios del SaaS
  user_tickets    → tickets de API de Mercado Público por usuario (cifrados)

Tablas modificadas:
  reglas_usuario  → agrega user_id (FK users.id)
  alertas_generadas → agrega user_id

Tablas compartidas (caché pública):
  licitaciones_snapshot → sin user_id (datos públicos de la API)
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from flask_login import UserMixin
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, JSON,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ═══════════════════════════════════════════════════════════════════════════════
# USER
# ═══════════════════════════════════════════════════════════════════════════════

class User(UserMixin, Base):
    __tablename__ = "users"

    id:             Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    email:          Mapped[str]  = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash:  Mapped[str]  = mapped_column(String(255), nullable=False)
    nombre:         Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    plan:           Mapped[str]  = mapped_column(String(30), default="free", nullable=False)
    # free | pro | enterprise
    activo:         Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fecha_registro: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    ultimo_acceso:  Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relaciones
    tickets: Mapped[list[UserTicket]]   = relationship("UserTicket", back_populates="user",
                                            cascade="all, delete-orphan")
    reglas:  Mapped[list[ReglaUsuario]] = relationship("ReglaUsuario", back_populates="user",
                                            cascade="all, delete-orphan", lazy="dynamic")
    alertas: Mapped[list[AlertaGenerada]] = relationship("AlertaGenerada", back_populates="user",
                                            cascade="all, delete-orphan", lazy="dynamic")

    # Flask-Login requiere get_id() → retorna str
    def get_id(self) -> str:
        return str(self.id)

    @property
    def ticket_activo(self) -> Optional["UserTicket"]:
        return next((t for t in self.tickets if t.activo), None)

    @property
    def es_pro(self) -> bool:
        return self.plan in ("pro", "enterprise")

    @property
    def limite_reglas(self) -> int:
        return 999 if self.es_pro else 3

    def __repr__(self) -> str:
        return f"<User {self.email} plan={self.plan}>"


# ═══════════════════════════════════════════════════════════════════════════════
# USER TICKET
# ═══════════════════════════════════════════════════════════════════════════════

class UserTicket(Base):
    __tablename__ = "user_tickets"

    id:              Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                       nullable=False)
    ticket_cifrado:  Mapped[str]  = mapped_column(Text, nullable=False)
    activo:          Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fecha_creacion:  Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="tickets")

    def get_ticket(self) -> str:
        """Descifra y retorna el ticket en texto plano."""
        from app.crypto import descifrar_ticket
        return descifrar_ticket(self.ticket_cifrado)

    def __repr__(self) -> str:
        return f"<UserTicket user_id={self.user_id} activo={self.activo}>"


# ═══════════════════════════════════════════════════════════════════════════════
# REGLA USUARIO (multi-tenant)
# ═══════════════════════════════════════════════════════════════════════════════

class ReglaUsuario(Base):
    __tablename__ = "reglas_usuario"

    id:                    Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:               Mapped[Optional[int]] = mapped_column(
                               Integer, ForeignKey("users.id", ondelete="CASCADE"),
                               nullable=True, index=True)   # nullable para migración
    nombre_regla:          Mapped[str]  = mapped_column(String(255), nullable=False)
    activa:                Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tipo_entidad:          Mapped[str]  = mapped_column(String(50), nullable=False)
    filtros:               Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    email_destino:         Mapped[str]  = mapped_column(String(500), nullable=False)
    fecha_creacion:        Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    fecha_ultima_ejecucion: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user:   Mapped[Optional[User]]         = relationship("User", back_populates="reglas")
    alertas: Mapped[list[AlertaGenerada]]  = relationship("AlertaGenerada", back_populates="regla",
                                               lazy="dynamic", cascade="all, delete-orphan")

    @property
    def emails_lista(self) -> list[str]:
        return [e.strip() for e in self.email_destino.split(",") if e.strip()]

    def __repr__(self) -> str:
        return f"<ReglaUsuario id={self.id} nombre='{self.nombre_regla}'>"


# ═══════════════════════════════════════════════════════════════════════════════
# ALERTA GENERADA (multi-tenant)
# ═══════════════════════════════════════════════════════════════════════════════

class AlertaGenerada(Base):
    __tablename__ = "alertas_generadas"
    __table_args__ = (
        UniqueConstraint("regla_id", "entidad_id", name="uq_regla_entidad"),
    )

    id:               Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:          Mapped[Optional[int]] = mapped_column(
                          Integer, ForeignKey("users.id", ondelete="CASCADE"),
                          nullable=True, index=True)
    regla_id:         Mapped[int]  = mapped_column(Integer,
                          ForeignKey("reglas_usuario.id", ondelete="CASCADE"), nullable=False)
    entidad_id:       Mapped[str]  = mapped_column(String(150), nullable=False, index=True)
    datos_resumen:    Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fecha_alerta:     Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    enviado_email:    Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mostrado_dashboard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user:  Mapped[Optional[User]]  = relationship("User", back_populates="alertas")
    regla: Mapped[ReglaUsuario]    = relationship("ReglaUsuario", back_populates="alertas")

    def __repr__(self) -> str:
        return f"<AlertaGenerada id={self.id} entidad='{self.entidad_id}'>"


# ═══════════════════════════════════════════════════════════════════════════════
# LICITACION SNAPSHOT (compartido — caché pública)
# ═══════════════════════════════════════════════════════════════════════════════

class LicitacionSnapshot(Base):
    __tablename__ = "licitaciones_snapshot"

    id:                  Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo:              Mapped[str]  = mapped_column(String(150), unique=True, nullable=False, index=True)
    tipo:                Mapped[str]  = mapped_column(String(50), nullable=False, default="licitacion")
    datos:               Mapped[dict] = mapped_column(JSON, nullable=False)
    fecha_publicacion:   Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    estado:              Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    region:              Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    monto_clp:           Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fecha_sincronizacion: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<LicitacionSnapshot codigo='{self.codigo}'>"


# ═══════════════════════════════════════════════════════════════════════════════
# USER CONFIG — preferencias de notificación por usuario
# ═══════════════════════════════════════════════════════════════════════════════

class UserConfig(Base):
    """Configuración de notificaciones y preferencias por usuario."""
    __tablename__ = "user_configs"

    id:              Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                       nullable=False, unique=True)
    # Modo de notificación: "realtime" (email por alerta) | "digest" (resumen diario)
    notif_mode:      Mapped[str]  = mapped_column(String(20), default="digest", nullable=False)
    digest_hora:     Mapped[int]  = mapped_column(Integer, default=8, nullable=False)  # hora UTC
    # Webhook global del usuario (opcional)
    webhook_url:     Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    webhook_activo:  Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Trial Pro
    trial_pro_hasta: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Notif por dashboard (siempre True por defecto)
    notif_dashboard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship("User", backref="config", uselist=False)

    def __repr__(self) -> str:
        return f"<UserConfig user_id={self.user_id} mode={self.notif_mode}>"


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK LOG — registro de envíos de webhook
# ═══════════════════════════════════════════════════════════════════════════════

class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id:           Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:      Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                     nullable=False)
    alerta_id:    Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    url:          Mapped[str]  = mapped_column(String(512), nullable=False)
    status_code:  Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ok:           Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    intentos:     Mapped[int]  = mapped_column(Integer, default=0, nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    creado_en:    Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:
        return f"<WebhookLog user_id={self.user_id} ok={self.ok}>"


# ═══════════════════════════════════════════════════════════════════════════════
# API QUOTA LOG — seguimiento de uso de cuota por usuario/día
# ═══════════════════════════════════════════════════════════════════════════════

class ApiQuotaLog(Base):
    __tablename__ = "api_quota_logs"
    __table_args__ = (UniqueConstraint("user_id", "fecha", name="uq_quota_user_fecha"),)

    id:        Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:   Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                  nullable=False)
    fecha:     Mapped[str]  = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    requests:  Mapped[int]  = mapped_column(Integer, default=0, nullable=False)
    limite:    Mapped[int]  = mapped_column(Integer, default=10000, nullable=False)

    def __repr__(self) -> str:
        return f"<ApiQuotaLog user_id={self.user_id} fecha={self.fecha} req={self.requests}>"
