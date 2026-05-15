"""YouTube reference channel and video models.

Separate from drive models — YouTube has different columns (youtube_video_id
vs google_file_id, channel_id vs connection_id, subtitle tracking, etc.).
Same status state machine as DriveFile for pipeline compatibility.
"""

from datetime import datetime
from typing import Optional, final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class YouTubeChannel(Base, UUIDMixin, TimestampMixin):
    """A YouTube channel registered for reference video indexing."""

    __tablename__ = "youtube_channels"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="YouTube channel ID (UC... format)",
    )
    channel_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Original URL (@handle or /channel/ format)",
    )
    channel_name: Mapped[str] = mapped_column(String(255), nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__: tuple[object, ...] = (
        UniqueConstraint(
            "org_id", "channel_id", name="uq_youtube_channels_org_channel"
        ),
        Index("ix_youtube_channels_org_id", "org_id"),
    )


@final
class YouTubeVideo(Base, UUIDMixin, TimestampMixin):
    """A YouTube video being processed through the reference pipeline.

    Status state machine:
        pending → downloading → uploading → transcoding → indexed → enriching → complete
                                                                              → failed
    """

    __tablename__ = "youtube_videos"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("youtube_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    youtube_video_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="YouTube video ID (typically 11 chars)",
    )
    video_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Internal video_id: yt_{sha256[:16]}",
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    publish_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    subtitle_language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Language code of extracted subtitle (e.g. 'ko')",
    )
    has_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_status: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        comment="pending|downloading|uploading|transcoding|indexed|enriching|complete|failed",
    )
    enrichment_status: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        default=dict,
        comment='Per-worker status: {"stt":"skipped","ocr":"complete",...}',
    )
    original_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="True after original + proxy deleted from S3 post-enrichment",
    )

    __table_args__: tuple[object, ...] = (
        UniqueConstraint(
            "org_id", "youtube_video_id", name="uq_youtube_videos_org_yt_id"
        ),
        Index("ix_youtube_videos_org_id", "org_id"),
        Index("ix_youtube_videos_channel_id", "channel_id"),
        Index("ix_youtube_videos_status", "processing_status"),
        Index("ix_youtube_videos_video_id", "video_id"),
    )
