from datetime import datetime
from typing import Any, final
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


# State machine for BlurJob.status. Enumerated in one place so the
# service, repository, tests, and migration all agree.
BLUR_STATUS_QUEUED = "queued"
BLUR_STATUS_RUNNING = "running"
BLUR_STATUS_DONE = "done"
BLUR_STATUS_FAILED = "failed"
BLUR_STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES: frozenset[str] = frozenset({BLUR_STATUS_QUEUED, BLUR_STATUS_RUNNING})
TERMINAL_STATUSES: frozenset[str] = frozenset({
    BLUR_STATUS_DONE, BLUR_STATUS_FAILED, BLUR_STATUS_CANCELLED,
})


@final
class BlurJob(Base, UUIDMixin, TimestampMixin):
    """One user-requested blur run on a single video.

    A user may create many jobs against the same video — each with
    different options — so blur state lives here rather than on
    ``drive_files``. Output S3 keys are per-job, which means retention
    and cancellation are safe: deleting one job's output never touches
    another's.
    """

    __tablename__ = "blur_jobs"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # State + options
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=BLUR_STATUS_QUEUED
    )
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    options_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Source
    source_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # proxy|original

    # Result (populated when status=done)
    blurred_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    manifest_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    detections_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lifecycle
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Worker lease (set by claim, cleared on completion)
    lease_token: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__: tuple[object, ...] = (
        Index("ix_blur_jobs_org_requested", "org_id", "requested_at"),
        Index("ix_blur_jobs_file_status", "file_id", "status"),
        Index(
            "ix_blur_jobs_active",
            "org_id", "status",
            postgresql_where=(status.in_([BLUR_STATUS_QUEUED, BLUR_STATUS_RUNNING])),
        ),
        Index(
            "ix_blur_jobs_dedupe",
            "org_id", "file_id", "options_hash", "requested_at",
        ),
    )
