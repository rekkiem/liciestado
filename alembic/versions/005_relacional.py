"""Obj5: modelo relacional organismo/licitacion/version/item/proveedor/adjudicacion.

Revision ID: 005_relacional
Revises: 004_sync_state
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_relacional"
down_revision = "004_sync_state"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "organismos" not in tables:
        op.create_table(
            "organismos",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("codigo", sa.String(40), nullable=False),
            sa.Column("nombre", sa.String(255), nullable=True),
            sa.Column("region", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("codigo", name="uq_organismos_codigo"),
        )
        op.create_index("ix_organismos_codigo", "organismos", ["codigo"], unique=True)

    if "licitaciones" not in tables:
        op.create_table(
            "licitaciones",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("codigo", sa.String(50), nullable=False),
            sa.Column("tipo", sa.String(30), nullable=False, server_default="licitacion"),
            sa.Column("titulo", sa.String(500), nullable=True),
            sa.Column("estado", sa.String(80), nullable=True),
            sa.Column("fecha_publicacion", sa.DateTime(), nullable=True),
            sa.Column("fecha_cierre", sa.DateTime(), nullable=True),
            sa.Column("monto_clp", sa.Integer(), nullable=True),
            sa.Column("organismo_id", sa.Integer(), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("link_detalle", sa.String(512), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["organismo_id"], ["organismos.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("codigo", name="uq_licitaciones_codigo"),
        )
        op.create_index("ix_licitaciones_codigo", "licitaciones", ["codigo"], unique=True)
        op.create_index("ix_licitaciones_fecha_publicacion", "licitaciones", ["fecha_publicacion"])
        op.create_index("ix_licitaciones_organismo_id", "licitaciones", ["organismo_id"])
        op.create_index("ix_licitaciones_content_hash", "licitaciones", ["content_hash"])

    if "licitacion_versiones" not in tables:
        op.create_table(
            "licitacion_versiones",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("licitacion_id", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("payload", _json_type(), nullable=False),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["licitacion_id"], ["licitaciones.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("licitacion_id", "content_hash", name="uq_lic_version_hash"),
        )
        op.create_index("ix_licitacion_versiones_licitacion_id", "licitacion_versiones", ["licitacion_id"])

    if "items" not in tables:
        op.create_table(
            "items",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("licitacion_id", sa.Integer(), nullable=False),
            sa.Column("codigo_item", sa.String(80), nullable=True),
            sa.Column("descripcion", sa.Text(), nullable=True),
            sa.Column("cantidad", sa.Numeric(18, 4), nullable=True),
            sa.Column("unidad", sa.String(40), nullable=True),
            sa.Column("monto_unitario", sa.Numeric(18, 2), nullable=True),
            sa.ForeignKeyConstraint(["licitacion_id"], ["licitaciones.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_items_licitacion_id", "items", ["licitacion_id"])

    if "proveedores" not in tables:
        op.create_table(
            "proveedores",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("rut", sa.String(12), nullable=False),
            sa.Column("nombre", sa.String(255), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("rut", name="uq_proveedores_rut"),
        )
        op.create_index("ix_proveedores_rut", "proveedores", ["rut"], unique=True)

    if "adjudicaciones" not in tables:
        op.create_table(
            "adjudicaciones",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("licitacion_id", sa.Integer(), nullable=False),
            sa.Column("proveedor_id", sa.Integer(), nullable=True),
            sa.Column("monto", sa.Numeric(18, 2), nullable=True),
            sa.Column("fecha", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["licitacion_id"], ["licitaciones.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["proveedor_id"], ["proveedores.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_adjudicaciones_licitacion_id", "adjudicaciones", ["licitacion_id"])
        op.create_index("ix_adjudicaciones_proveedor_id", "adjudicaciones", ["proveedor_id"])
        op.create_index("ix_adj_lic_prov", "adjudicaciones", ["licitacion_id", "proveedor_id"])


def downgrade() -> None:
    for t in ("adjudicaciones", "items", "licitacion_versiones", "licitaciones", "proveedores", "organismos"):
        op.drop_table(t)
