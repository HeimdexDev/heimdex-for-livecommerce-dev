"""Add enrichment tracking columns to drive_files

Revision ID: 013_add_enrichment_tracking
Revises: 012_create_drive_tables
Create Date: 2026-02-19

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_add_enrichment_tracking"
down_revision: str | None = "012_create_drive_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drive_files", sa.Column("enrichment_state", sa.String(32), nullable=True))
    op.add_column("drive_files", sa.Column("stt_status", sa.String(32), nullable=True))
    op.add_column("drive_files", sa.Column("ocr_status", sa.String(32), nullable=True))
    op.add_column("drive_files", sa.Column("audio_s3_key", sa.Text(), nullable=True))
    op.add_column("drive_files", sa.Column("keyframe_s3_prefix", sa.Text(), nullable=True))
    op.add_column("drive_files", sa.Column("enrichment_error", sa.Text(), nullable=True))
    op.add_column(
        "drive_files",
        sa.Column("enrichment_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_drive_files_enrichment_state", "drive_files", ["enrichment_state"])


def downgrade() -> None:
    op.drop_index("ix_drive_files_enrichment_state", table_name="drive_files")
    op.drop_column("drive_files", "enrichment_updated_at")
    op.drop_column("drive_files", "enrichment_error")
    op.drop_column("drive_files", "keyframe_s3_prefix")
    op.drop_column("drive_files", "audio_s3_key")
    op.drop_column("drive_files", "ocr_status")
    op.drop_column("drive_files", "stt_status")
    op.drop_column("drive_files", "enrichment_state")
