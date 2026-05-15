"""Add lease_token and lease_expires_at columns to drive_files

Revision ID: 020_add_lease_token_columns
Revises: 019_make_drive_name_nullable
Create Date: 2026-02-24

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "020_add_lease_token_columns"
down_revision: str | None = "019_make_drive_name_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drive_files",
        sa.Column("lease_token", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "drive_files",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("drive_files", "lease_expires_at")
    op.drop_column("drive_files", "lease_token")
