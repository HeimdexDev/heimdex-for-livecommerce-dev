from uuid import UUID as PyUUID

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class SceneOverride(Base, UUIDMixin, TimestampMixin):
    """Per-field user overrides for scene captions, transcripts, and tags.

    NULL override columns mean "use the worker-generated value".
    Only non-NULL columns with their field name in overridden_fields
    represent active user edits.
    """

    __tablename__ = "scene_overrides"

    org_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scene_id: Mapped[str] = mapped_column(String(128), nullable=False)
    video_id: Mapped[str] = mapped_column(String(128), nullable=False)
    edited_by: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=False,
    )

    # Override values — NULL means "use worker value"
    scene_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaker_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Original worker values — captured on first override for reset
    original_scene_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_transcript_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_speaker_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_ai_tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Comma-separated field names that are actively overridden
    overridden_fields: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("org_id", "scene_id", name="uq_scene_overrides_org_scene"),
        Index("ix_scene_overrides_org_video", "org_id", "video_id"),
    )
