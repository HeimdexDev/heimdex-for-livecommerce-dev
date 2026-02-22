"""Add heartbeat timestamp to drive_files

Revision ID: 015_add_heartbeat_at
Revises: 014_add_caption_tracking
Create Date: 2026-02-22

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015_add_heartbeat_at"
down_revision: str | None = "014_add_caption_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drive_files", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("drive_files", "last_heartbeat_at")
