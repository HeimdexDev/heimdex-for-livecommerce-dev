"""Add sync_requested_at to drive_connections

Revision ID: 017_add_sync_requested_at
Revises: 016_idempotency_and_cluster_unique
Create Date: 2026-02-22

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017_add_sync_requested_at"
down_revision: str | None = "016_idempotency_and_cluster_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drive_connections",
        sa.Column("sync_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("drive_connections", "sync_requested_at")
