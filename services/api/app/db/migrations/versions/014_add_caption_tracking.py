"""Add caption tracking columns to drive_files

Revision ID: 014_add_caption_tracking
Revises: 013_add_enrichment_tracking
Create Date: 2026-02-20

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_add_caption_tracking"
down_revision: str | None = "013_add_enrichment_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drive_files", sa.Column("caption_status", sa.String(32), nullable=True))
    op.add_column("drive_files", sa.Column("caption_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("drive_files", "caption_error")
    op.drop_column("drive_files", "caption_status")
