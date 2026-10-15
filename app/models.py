"""
app/models.py — Modelos ORM multi-tenant.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from flask_login import UserMixin
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

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

    tickets: Mapped[list["UserTicket"]] = relationship("UserTicket", back_populates="user",
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
        if self.plan in ("pro", "enterprise"):
            return True
        cfg = self.__dict__.get("config", None)
        if cfg is None:
            return False
        hasta = getattr(cfg, "trial_pro_hasta", None)
        if hasta is None:
            return False
        if hasta.tzinfo is None:
            hasta = hasta.replace(tzinfo=timezone.utc)
        return hasta > datetime.now(timezone.utc)

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

    user: Mapped[User] = relationship("User", back_populates="tickets")

    def get_ticket(self) -> str:
        from app.crypto import descifrar_ticket
        return descifrar_ticket(self.ticket_cifrado)

    def __repr__(self) -> str:
        return f"<UserTicket user_id={self.user_id} activo={self.activo}>"


class ReglaUsuario(Base):
    __tablename__ = "reglas_usuario"

    id:                    Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:               Mapped[Optional[int]] = mapped_column(
                               Integer, ForeignKey("users.id", ondelete="CASCADE"),
                               nullable=True, index=True)
    nombre_regla:          Mapped[str]  = mapped_column(String(255), nullable=False)
    activa:                Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tipo_entidad:          Mapped[str]  = mapped_column(String(50), nullable=False)
    filtros:               Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    email_destino:         Mapped[str]  = mapped_column(String(500), nullable=False)
    fecha_creacion:        Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    fecha_ultima_ejecucion: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user:   Mapped[Optional[User]]         = relationship("User", back_populates="reglas")
    alertas: Mapped[list["AlertaGenerada"]]  = relationship("AlertaGenerada", back_populates="regla",
                                               lazy="dynamic", cascade="all, delete-orphan")

    @property
    def emails_lista(self) -> list[str]:
        return [e.strip() for e in self.email_destino.split(",") if e.strip()]

    def __repr__(self) -> str:
        return f"<ReglaUsuario id={self.id} nombre='{self.nombre_regla}'>"


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
    tipo_entidad:     Mapped[str]  = mapped_column(String(50), nullable=False, default="licitacion")
    datos_resumen:    Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fecha_alerta:     Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    enviado_email:    Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mostrado_dashboard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user:  Mapped[Optional[User]]  = relationship("User", back_populates="alertas")
    regla: Mapped[ReglaUsuario]    = relationship("ReglaUsuario", back_populates="alertas")

    def __repr__(self) -> str:
        return f"<AlertaGenerada id={self.id} entidad='{self.entidad_id}'>"


class LicitacionSnapshot(Base):
    __tablename__ = "licitaciones_snapshot"

    id:                  Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo:              Mapped[str]  = mapped_column(String(50), unique=True, nullable=False, index=True)
    tipo:                Mapped[str]  = mapped_column(String(30), default="licitacion", nullable=False)
    datos:               Mapped[dict] = mapped_column(JSON, nullable=False)
    fecha_publicacion:   Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    estado:              Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    region:              Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    monto_clp:           Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fecha_sincronizacion: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    detalle_obtenido_en: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    enrich_attempts:     Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_enrich_error:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<LicitacionSnapshot codigo='{self.codigo}'>"


class UserConfig(Base):
    __tablename__ = "user_configs"

    id:              Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                       nullable=False, unique=True)
    notif_mode:      Mapped[str]  = mapped_column(String(20), default="digest", nullable=False)
    digest_hora:     Mapped[int]  = mapped_column(Integer, default=8, nullable=False)
    webhook_url:     Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    webhook_activo:  Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trial_pro_hasta: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notif_dashboard: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    webhook_secret:  Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    user: Mapped["User"] = relationship("User", backref=backref("config", uselist=False))

    def __repr__(self) -> str:
        return f"<UserConfig user_id={self.user_id} mode={self.notif_mode}>"


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id:           Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:      Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                   nullable=False, index=True)
    alerta_id:    Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    url:          Mapped[str]  = mapped_column(String(512), nullable=False)
    status_code:  Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ok:           Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    intentos:     Mapped[int]  = mapped_column(Integer, default=1, nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fecha_envio:  Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:
        return f"<WebhookLog user={self.user_id} ok={self.ok}>"


class ApiQuotaLog(Base):
    __tablename__ = "api_quota_logs"

    id:         Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:    Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                                  nullable=False, index=True)
    fecha:      Mapped[str]  = mapped_column(String(10), nullable=False)
    requests:   Mapped[int]  = mapped_column(Integer, default=0, nullable=False)
    limite:     Mapped[int]  = mapped_column(Integer, default=10000, nullable=False)
    creado_en:  Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "fecha", name="uq_quota_user_fecha"),)

    def __repr__(self) -> str:
        return f"<ApiQuotaLog user={self.user_id} fecha={self.fecha} req={self.requests}>"


class NotificationOutbox(Base):
    """Cola durable (email/webhook). Estados: pendiente|procesando|enviado|fallido."""
    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    alerta_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    destino: Mapped[str] = mapped_column(String(512), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente")
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    enviado_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_outbox_idempotency"),
        Index("ix_outbox_claim", "estado", "next_retry_at"),
    )

    def __repr__(self) -> str:
        return f"<Outbox {self.id} {self.canal} {self.estado} key={self.idempotency_key[:16]}>"


class SyncRun(Base):
    """Corrida de sync/enrich por día (Obj4). estado: completo|incompleto|error."""
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_kind_fecha", "kind", "fecha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    fecha: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="completo")
    motivo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    items_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_fail: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<SyncRun {self.kind} {self.fecha} {self.estado}>"


class ApiQuotaDaily(Base):
    """Cuota global diaria del ticket (Obj4). Persistida; no solo RAM."""
    __tablename__ = "api_quota_daily"

    fecha: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limite: Mapped[int] = mapped_column(Integer, nullable=False, default=10_000)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    def __repr__(self) -> str:
        return f"<ApiQuotaDaily {self.fecha} {self.requests}/{self.limite}>"


# ─── Obj5: modelo relacional (snapshot JSON sigue vigente) ───────────────────

class Organismo(Base):
    __tablename__ = "organismos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    nombre: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    region: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    def __repr__(self) -> str:
        return f"<Organismo codigo={self.codigo!r}>"


class Licitacion(Base):
    __tablename__ = "licitaciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, default="licitacion")
    titulo: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    estado: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    fecha_publicacion: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    fecha_cierre: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    monto_clp: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    organismo_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("organismos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    link_detalle: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<Licitacion codigo={self.codigo!r}>"


class LicitacionVersion(Base):
    __tablename__ = "licitacion_versiones"
    __table_args__ = (
        UniqueConstraint("licitacion_id", "content_hash", name="uq_lic_version_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    licitacion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    licitacion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    codigo_item: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    descripcion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cantidad: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    unidad: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    monto_unitario: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)


class Proveedor(Base):
    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rut: Mapped[str] = mapped_column(String(12), unique=True, nullable=False, index=True)
    nombre: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<Proveedor rut={self.rut!r}>"


class Adjudicacion(Base):
    __tablename__ = "adjudicaciones"
    __table_args__ = (
        Index("ix_adj_lic_prov", "licitacion_id", "proveedor_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    licitacion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("licitaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proveedor_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("proveedores.id", ondelete="SET NULL"), nullable=True, index=True
    )
    monto: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    fecha: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
