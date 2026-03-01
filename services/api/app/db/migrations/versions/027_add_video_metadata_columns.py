"""Add video metadata columns to drive_files

Stores fps, width, and height extracted via ffprobe during video ingest.
These are used by the FCPXML export feature to generate frame-accurate timelines.

Revision ID: 027_add_video_metadata_columns
Revises: 026_add_web_view_link
Create Date: 2026-03-01

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "027_add_video_metadata_columns"
down_revision: str | None = "026_add_web_view_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drive_files", sa.Column("video_fps", sa.Float(), nullable=True))
    op.add_column("drive_files", sa.Column("video_width", sa.Integer(), nullable=True))
    op.add_column("drive_files", sa.Column("video_height", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("drive_files", "video_height")
    op.drop_column("drive_files", "video_width")
    op.drop_column("drive_files", "video_fps")
