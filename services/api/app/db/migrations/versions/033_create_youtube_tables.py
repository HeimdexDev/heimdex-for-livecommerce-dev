"""Create youtube_channels and youtube_videos tables

YouTube reference video feature — separate tables from drive_files.
Different columns (youtube_video_id vs google_file_id, channel_id vs
connection_id, subtitle tracking).  Same status state machine for
pipeline compatibility.

Revision ID: 033_create_youtube_tables
Revises: 032_add_missing_indexes
Create Date: 2026-03-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "033_create_youtube_tables"
down_revision: str | None = "032_add_missing_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── youtube_channels ──────────────────────────────────────────────
    op.create_table(
        "youtube_channels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel_id", sa.String(64), nullable=False),
        sa.Column("channel_url", sa.String(500), nullable=True),
        sa.Column("channel_name", sa.String(255), nullable=False),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("video_count", sa.Integer, server_default="0"),
        sa.Column(
            "last_synced_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("sync_enabled", sa.Boolean, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "org_id", "channel_id", name="uq_youtube_channels_org_channel"
        ),
    )
    op.create_index(
        "ix_youtube_channels_org_id", "youtube_channels", ["org_id"]
    )

    # ── youtube_videos ────────────────────────────────────────────────
    op.create_table(
        "youtube_videos",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("youtube_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("youtube_video_id", sa.String(32), nullable=False),
        sa.Column("video_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column(
            "publish_date", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("subtitle_language", sa.String(10), nullable=True),
        sa.Column("has_subtitles", sa.Boolean, server_default="false"),
        sa.Column(
            "processing_status",
            sa.String(32),
            server_default="pending",
        ),
        sa.Column("enrichment_status", JSONB, server_default="{}"),
        sa.Column("original_deleted", sa.Boolean, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "org_id",
            "youtube_video_id",
            name="uq_youtube_videos_org_yt_id",
        ),
    )
    op.create_index(
        "ix_youtube_videos_org_id", "youtube_videos", ["org_id"]
    )
    op.create_index(
        "ix_youtube_videos_channel_id", "youtube_videos", ["channel_id"]
    )
    op.create_index(
        "ix_youtube_videos_status",
        "youtube_videos",
        ["processing_status"],
    )
    op.create_index(
        "ix_youtube_videos_video_id", "youtube_videos", ["video_id"]
    )


def downgrade() -> None:
    op.drop_table("youtube_videos")
    op.drop_table("youtube_channels")
