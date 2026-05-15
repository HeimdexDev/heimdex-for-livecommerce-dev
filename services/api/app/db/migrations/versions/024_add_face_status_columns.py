"""Add face_status and face_error columns to drive_files

Supports face enrichment tracking via the enrichment job claim/status system.

Revision ID: 024_add_face_status_columns
Revises: 023_add_face_identity_tables
Create Date: 2026-02-27

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "024_add_face_status_columns"
down_revision: str | None = "023_add_face_identity_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drive_files", sa.Column("face_status", sa.String(32), nullable=True))
    op.add_column("drive_files", sa.Column("face_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("drive_files", "face_error")
    op.drop_column("drive_files", "face_status")
