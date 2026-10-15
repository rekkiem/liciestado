"""Obj3 fix: outbox lease (procesando) + índice claim compuesto

Revision ID: 003_outbox_lease
Revises: 002_outbox
Create Date: 2026-10-14
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_outbox_lease"
down_revision: Union[str, None] = "002_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("notification_outbox") as batch:
        batch.add_column(sa.Column("locked_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("locked_by", sa.String(length=64), nullable=True))
    op.drop_index("ix_notification_outbox_estado", table_name="notification_outbox")
    op.create_index("ix_outbox_claim", "notification_outbox", ["estado", "next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_claim", table_name="notification_outbox")
    op.create_index("ix_notification_outbox_estado", "notification_outbox", ["estado"])
    with op.batch_alter_table("notification_outbox") as batch:
        batch.drop_column("locked_by")
        batch.drop_column("locked_at")
