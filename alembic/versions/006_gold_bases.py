"""Obj6: gold_bases para anotacion de bases PDF.

Revision ID: 006_gold_bases
Revises: 005_relacional
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006_gold_bases"
down_revision = "005_relacional"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "gold_bases" in set(insp.get_table_names()):
        return
    op.create_table(
        "gold_bases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("codigo", sa.String(50), nullable=False),
        sa.Column("vertical", sa.String(30), nullable=False),
        sa.Column("titulo", sa.String(500), nullable=True),
        sa.Column("pdf_path", sa.String(512), nullable=True),
        sa.Column("anotacion", _json_type(), nullable=False),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", "vertical", name="uq_gold_codigo_vertical"),
    )
    op.create_index("ix_gold_bases_codigo", "gold_bases", ["codigo"])


def downgrade() -> None:
    op.drop_table("gold_bases")
