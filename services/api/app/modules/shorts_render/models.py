from datetime import datetime
from typing import Any, final
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


@final
class ShortsRenderJob(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "shorts_render_jobs"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="queued"
    )
    input_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # sha256 of the normalized composition spec. Used by the dedupe query
    # to collapse accidental double-submissions of the same composition
    # from the same user within a short time window. NULL for legacy rows
    # created before this column existed.
    composition_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    # Refinement chain (migration 056). Used by the post-render Whisper
    # subtitle refinement hook to link a parent render to the refined
    # render produced from its output MP4.
    #
    # ``replaced_by_render_job_id`` (forward pointer): the parent points
    # to the refined child once that child completes. NULL while the
    # parent is canonical.
    # ``refined_from_render_job_id`` (back pointer): the refined child
    # points back at its parent. Used by the cascade-idempotency guard
    # in :mod:`app.modules.shorts_render.refinement_service` (PR 4) to
    # short-circuit recursive refinement attempts.
    # ``refinement_source``: which path produced the current row's
    # ``input_spec.subtitles``. CHECK-constrained to {'whisper',
    # 'manual_edit'}. NULL means "default speaker_transcript timing
    # (no manual or LLM refinement applied)" — the most common state
    # for non-refined rows.
    #
    # All three columns ship nullable so existing rows are unaffected.
    # ON DELETE SET NULL on both FKs so deleting one render in the
    # chain doesn't cascade-delete its parent or child — the chain
    # simply breaks at the deleted node.
    #
    # NO SQLAlchemy ``relationship()`` defined here on purpose: the
    # refinement service queries by id directly. Adding eager-loading
    # relationships would change the cost of every existing
    # ``ShortsRenderJob`` query in the codebase.
    replaced_by_render_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shorts_render_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    refined_from_render_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shorts_render_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    refinement_source: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )

    __table_args__: tuple[object, ...] = (
        Index("ix_shorts_render_jobs_org_id_user_id", "org_id", "user_id"),
        Index(
            "ix_shorts_render_jobs_dedupe",
            "org_id",
            "user_id",
            "composition_hash",
            "created_at",
        ),
        # Partial index supports the "have we already refined this
        # parent?" guard query without bloating writes for the common
        # case (no refinement pending).
        Index(
            "ix_shorts_render_jobs_replaced_by",
            "replaced_by_render_job_id",
            postgresql_where="replaced_by_render_job_id IS NOT NULL",
        ),
    )
