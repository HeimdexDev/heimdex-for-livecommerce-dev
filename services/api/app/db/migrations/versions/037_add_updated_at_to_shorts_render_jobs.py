"""Add updated_at column to shorts_render_jobs for TimestampMixin compatibility

Revision ID: 037_add_updated_at_to_shorts_render_jobs
Revises: 036_add_shorts_render_jobs_table
Create Date: 2026-03-18

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "037_add_updated_at_to_shorts_render_jobs"
down_revision: str | None = "036_add_shorts_render_jobs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shorts_render_jobs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("shorts_render_jobs", "updated_at")
