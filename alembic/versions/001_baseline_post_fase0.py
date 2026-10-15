"""Baseline post–Fase 0: schema completo actual (alineado a app/models.py).

Revision ID: 001_baseline
Revises:
Create Date: 2026-10-14

Architect fix: server_default boolean con sa.true()/sa.false() (no text 1/0).
fecha_alerta NOT NULL alineado al modelo.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=True),
        sa.Column("plan", sa.String(length=30), nullable=False, server_default="free"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fecha_registro", sa.DateTime(), nullable=False),
        sa.Column("ultimo_acceso", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_tickets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("ticket_cifrado", sa.Text(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("fecha_creacion", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("notif_mode", sa.String(length=20), nullable=False, server_default="digest"),
        sa.Column("digest_hora", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("webhook_url", sa.String(length=512), nullable=True),
        sa.Column("webhook_activo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trial_pro_hasta", sa.DateTime(), nullable=True),
        sa.Column("notif_dashboard", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "reglas_usuario",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("nombre_regla", sa.String(length=255), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("tipo_entidad", sa.String(length=50), nullable=False),
        sa.Column("filtros", sa.JSON(), nullable=False),
        sa.Column("email_destino", sa.String(length=500), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(), nullable=False),
        sa.Column("fecha_ultima_ejecucion", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reglas_usuario_user_id", "reglas_usuario", ["user_id"])

    op.create_table(
        "licitaciones_snapshot",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("codigo", sa.String(length=50), nullable=False),
        sa.Column("tipo", sa.String(length=30), nullable=False, server_default="licitacion"),
        sa.Column("datos", sa.JSON(), nullable=False),
        sa.Column("fecha_publicacion", sa.DateTime(), nullable=True),
        sa.Column("estado", sa.String(length=80), nullable=True),
        sa.Column("region", sa.Integer(), nullable=True),
        sa.Column("monto_clp", sa.Integer(), nullable=True),
        sa.Column("fecha_sincronizacion", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_licitaciones_snapshot_codigo", "licitaciones_snapshot", ["codigo"], unique=True)
    op.create_index("ix_licitaciones_snapshot_fecha_publicacion", "licitaciones_snapshot", ["fecha_publicacion"])

    op.create_table(
        "alertas_generadas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("regla_id", sa.Integer(), nullable=False),
        sa.Column("entidad_id", sa.String(length=150), nullable=False),
        sa.Column("tipo_entidad", sa.String(length=50), nullable=False, server_default="licitacion"),
        sa.Column("datos_resumen", sa.JSON(), nullable=False),
        sa.Column("fecha_alerta", sa.DateTime(), nullable=False),
        sa.Column("enviado_email", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mostrado_dashboard", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["regla_id"], ["reglas_usuario.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("regla_id", "entidad_id", name="uq_regla_entidad"),
    )
    op.create_index("ix_alertas_generadas_user_id", "alertas_generadas", ["user_id"])
    op.create_index("ix_alertas_generadas_entidad_id", "alertas_generadas", ["entidad_id"])
    op.create_index("ix_alertas_generadas_fecha_alerta", "alertas_generadas", ["fecha_alerta"])

    op.create_table(
        "webhook_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("alerta_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("fecha_envio", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_logs_user_id", "webhook_logs", ["user_id"])

    op.create_table(
        "api_quota_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.String(length=10), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limite", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "fecha", name="uq_quota_user_fecha"),
    )
    op.create_index("ix_api_quota_logs_user_id", "api_quota_logs", ["user_id"])


def downgrade() -> None:
    op.drop_table("api_quota_logs")
    op.drop_table("webhook_logs")
    op.drop_table("alertas_generadas")
    op.drop_table("licitaciones_snapshot")
    op.drop_table("reglas_usuario")
    op.drop_table("user_configs")
    op.drop_table("user_tickets")
    op.drop_table("users")
