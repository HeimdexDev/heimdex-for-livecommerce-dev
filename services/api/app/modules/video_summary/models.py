"""SQLAlchemy model for video-level AI summaries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class VideoSummary(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "video_summaries"

    org_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False)
    video_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # AI-generated summary
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    model: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False, server_default="v1")

    # User override (NULL = use AI summary)
    summary_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_by: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    scene_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")

    __table_args__ = (
        UniqueConstraint("org_id", "video_id", name="uq_video_summaries_org_video"),
        Index("ix_video_summaries_org_id", "org_id"),
    )

    @property
    def effective_summary(self) -> str:
        return self.summary_override if self.summary_override is not None else self.summary

    @property
    def is_edited(self) -> bool:
        return self.summary_override is not None
