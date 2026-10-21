"""Obj4: sync_runs, api_quota_daily, enrich attempts on snapshot

Revision ID: 004_sync_state
Revises: 003_outbox_lease
Create Date: 2026-10-15
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "004_sync_state"
down_revision: Union[str, None] = "003_outbox_lease"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    if "sync_runs" not in tables:
        op.create_table(
            "sync_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("fecha", sa.String(10), nullable=False),
            sa.Column("estado", sa.String(20), nullable=False, server_default="completo"),
            sa.Column("motivo", sa.Text(), nullable=True),
            sa.Column("items_ok", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("items_fail", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_sync_runs_kind_fecha", "sync_runs", ["kind", "fecha"])
        op.create_index("ix_sync_runs_fecha", "sync_runs", ["fecha"])

    if "api_quota_daily" not in tables:
        op.create_table(
            "api_quota_daily",
            sa.Column("fecha", sa.String(10), primary_key=True),
            sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("limite", sa.Integer(), nullable=False, server_default="10000"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    cols = {c["name"] for c in insp.get_columns("licitaciones_snapshot")} if "licitaciones_snapshot" in tables else set()
    with op.batch_alter_table("licitaciones_snapshot") as batch:
        if "detalle_obtenido_en" not in cols:
            batch.add_column(sa.Column("detalle_obtenido_en", sa.DateTime(), nullable=True))
        if "enrich_attempts" not in cols:
            batch.add_column(sa.Column("enrich_attempts", sa.Integer(), nullable=False, server_default="0"))
        if "last_enrich_error" not in cols:
            batch.add_column(sa.Column("last_enrich_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("licitaciones_snapshot") as batch:
        batch.drop_column("last_enrich_error")
        batch.drop_column("enrich_attempts")
        batch.drop_column("detalle_obtenido_en")
    op.drop_table("api_quota_daily")
    op.drop_index("ix_sync_runs_fecha", table_name="sync_runs")
    op.drop_index("ix_sync_runs_kind_fecha", table_name="sync_runs")
    op.drop_table("sync_runs")
