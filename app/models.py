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


class User(UserMixin, Base):
    __tablename__ = "users"

    id:             Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    email:          Mapped[str]  = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash:  Mapped[str]  = mapped_column(String(255), nullable=False)
    nombre:         Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    plan:           Mapped[str]  = mapped_column(String(30), default="free", nullable=False)
    activo:         Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin:       Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fecha_registro: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    ultimo_acceso:  Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    tickets: Mapped[list["UserTicket"]]   = relationship("UserTicket", back_populates="user",
                                            cascade="all, delete-orphan")
    reglas:  Mapped[list["ReglaUsuario"]] = relationship("ReglaUsuario", back_populates="user",
                                            cascade="all, delete-orphan", lazy="dynamic")
    alertas: Mapped[list["AlertaGenerada"]] = relationship("AlertaGenerada", back_populates="user",
                                            cascade="all, delete-orphan", lazy="dynamic")

    def get_id(self) -> str:
        return str(self.id)

    @property
    def ticket_activo(self) -> Optional["UserTicket"]:
        return next((t for t in self.tickets if t.activo), None)

    @property
    def es_pro(self) -> bool:
        """Pro permanente o trial activo (trial_pro_hasta en UserConfig)."""
        if self.plan in ("pro", "enterprise"):
            return True
        try:
            from app.database import get_db
            from datetime import datetime
            with get_db() as db:
                cfg = db.query(UserConfig).filter_by(user_id=self.id).first()
                if cfg and cfg.trial_pro_hasta and cfg.trial_pro_hasta > datetime.utcnow():
                    return True
        except Exception:
            pass
        return False

    @property
    def limite_reglas(self) -> int:
        return 999 if self.es_pro else 3

    def __repr__(self) -> str:
        return f"<User {self.email} plan={self.plan}>"


class UserTicket(Base):
    __tablename__ = "user_tickets"

    id:              Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                       nullable=False)
    ticket_cifrado:  Mapped[str]  = mapped_column(Text, nullable=False)
    activo:          Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fecha_creacion:  Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="tickets")

    def get_ticket(self) -> str:
        from app.crypto import descifrar_ticket
        return descifrar_ticket(self.ticket_cifrado)

    def __repr__(self) -> str:
        return f"<UserTicket user_id={self.user_id} activo={self.activo}>"


class ReglaUsuario(Base):
    __tablename__ = "reglas_usuario"

    id:              Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                       nullable=False, index=True)
    nombre:          Mapped[str]  = mapped_column(String(120), nullable=False)
    tipo_entidad:    Mapped[str]  = mapped_column(String(30), default="licitacion", nullable=False)
    filtros:         Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    email_destino:   Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    activo:          Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fecha_creacion:  Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="reglas")

    def __repr__(self) -> str:
        return f"<ReglaUsuario {self.nombre} user_id={self.user_id}>"


class AlertaGenerada(Base):
    __tablename__ = "alertas_generadas"

    id:              Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                       nullable=False, index=True)
    regla_id:        Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("reglas_usuario.id", ondelete="SET NULL"), nullable=True)
    entidad_id:      Mapped[str]  = mapped_column(String(64), nullable=False, index=True)
    tipo_entidad:    Mapped[str]  = mapped_column(String(30), default="licitacion", nullable=False)
    datos_resumen:   Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fecha_alerta:    Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    enviado_email:   Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="alertas")

    def __repr__(self) -> str:
        return f"<AlertaGenerada {self.entidad_id} user_id={self.user_id}>"


class LicitacionSnapshot(Base):
    __tablename__ = "licitaciones_snapshot"

    id:                   Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo:               Mapped[str]  = mapped_column(String(64), nullable=False, index=True)
    tipo:                 Mapped[str]  = mapped_column(String(30), default="licitacion", nullable=False)
    datos:                Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    region:               Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    monto_clp:            Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    estado:               Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    fecha_sincronizacion: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:
        return f"<LicitacionSnapshot {self.codigo}>"


class UserConfig(Base):
    __tablename__ = "user_configs"

    id:              Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                       nullable=False, unique=True)
    notif_mode:      Mapped[str]  = mapped_column(String(30), default="digest", nullable=False)
    webhook_url:     Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    webhook_activo:  Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trial_pro_hasta: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notif_dashboard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship("User", backref="config", uselist=False)

    def __repr__(self) -> str:
        return f"<UserConfig user_id={self.user_id} mode={self.notif_mode}>"


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id:           Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:      Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    alerta_id:    Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    url:          Mapped[str]  = mapped_column(String(512), nullable=False)
    status_code:  Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ok:           Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    intentos:     Mapped[int]  = mapped_column(Integer, default=0, nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    creado_en:    Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:
        return f"<WebhookLog user_id={self.user_id} ok={self.ok}>"


class ApiQuotaLog(Base):
    __tablename__ = "api_quota_logs"
    __table_args__ = (UniqueConstraint("user_id", "fecha", name="uq_quota_user_fecha"),)

    id:        Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:   Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fecha:     Mapped[str]  = mapped_column(String(10), nullable=False)
    requests:  Mapped[int]  = mapped_column(Integer, default=0, nullable=False)
    limite:    Mapped[int]  = mapped_column(Integer, default=10000, nullable=False)

    def __repr__(self) -> str:
        return f"<ApiQuotaLog user_id={self.user_id} fecha={self.fecha} req={self.requests}>"
