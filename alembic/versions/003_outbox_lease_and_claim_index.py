"""Obj3 fix: outbox lease (procesando) + índice claim compuesto

Revision ID: 003_outbox_lease
Revises: 002_outbox
Create Date: 2026-10-14

Idempotente: soporta BD donde la tabla salió de create_all (sin índice 002).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "003_outbox_lease"
down_revision: Union[str, None] = "002_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("notification_outbox")}
    indexes = {ix["name"] for ix in insp.get_indexes("notification_outbox")}

    with op.batch_alter_table("notification_outbox") as batch:
        if "locked_at" not in cols:
            batch.add_column(sa.Column("locked_at", sa.DateTime(), nullable=True))
        if "locked_by" not in cols:
            batch.add_column(sa.Column("locked_by", sa.String(length=64), nullable=True))

    if "ix_notification_outbox_estado" in indexes:
        op.drop_index("ix_notification_outbox_estado", table_name="notification_outbox")
    if "ix_outbox_claim" not in indexes:
        op.create_index("ix_outbox_claim", "notification_outbox", ["estado", "next_retry_at"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("notification_outbox")}
    indexes = {ix["name"] for ix in insp.get_indexes("notification_outbox")}

    if "ix_outbox_claim" in indexes:
        op.drop_index("ix_outbox_claim", table_name="notification_outbox")
    if "ix_notification_outbox_estado" not in indexes:
        op.create_index("ix_notification_outbox_estado", "notification_outbox", ["estado"])
    with op.batch_alter_table("notification_outbox") as batch:
        if "locked_by" in cols:
            batch.drop_column("locked_by")
        if "locked_at" in cols:
            batch.drop_column("locked_at")
