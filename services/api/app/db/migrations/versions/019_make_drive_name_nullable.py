"""Make drive_name nullable for folder-scoped connections

Revision ID: 019_make_drive_name_nullable
Revises: 018_add_drive_oauth_support
Create Date: 2026-02-23

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "019_make_drive_name_nullable"
down_revision: str | None = "018_add_drive_oauth_support"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "drive_connections",
        "drive_name",
        existing_type=sa.String(length=500),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(sa.text("UPDATE drive_connections SET drive_name = '' WHERE drive_name IS NULL"))
    op.alter_column(
        "drive_connections",
        "drive_name",
        existing_type=sa.String(length=500),
        nullable=False,
    )
