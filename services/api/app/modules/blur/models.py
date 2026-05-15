from datetime import datetime
from typing import Any, final
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


# State machine for BlurJob.status AND BlurExport.status — they share
# the same five-state pattern (queued → running → {done, failed,
# cancelled}), so the constants and the active/terminal sets are
# reused on both sides.
BLUR_STATUS_QUEUED = "queued"
BLUR_STATUS_RUNNING = "running"
BLUR_STATUS_DONE = "done"
BLUR_STATUS_FAILED = "failed"
BLUR_STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES: frozenset[str] = frozenset({BLUR_STATUS_QUEUED, BLUR_STATUS_RUNNING})
TERMINAL_STATUSES: frozenset[str] = frozenset({
    BLUR_STATUS_DONE, BLUR_STATUS_FAILED, BLUR_STATUS_CANCELLED,
})

# Blur job phase — written by the worker via the internal progress
# heartbeat endpoint, read by the frontend to label the progress bar.
# Mirrors heimdex_media_contracts.blur.BlurJobPhase.
BLUR_PHASE_QUEUED = "queued"
BLUR_PHASE_INITIALIZING = "initializing"
BLUR_PHASE_DETECTING = "detecting"
BLUR_PHASE_ENCODING = "encoding"
BLUR_PHASE_UPLOADING = "uploading"
BLUR_PHASE_FINALIZING = "finalizing"


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
    # v0.10: per-category FFV1 mask videos uploaded by the worker. Used
    # by BlurExportService to compose a ProRes 4444 alpha layer on
    # demand without re-running OWLv2. Populated only when the pipeline
    # ran with ``emit_masks=True``; nullable so old rows keep validating.
    mask_s3_keys: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    detections_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Live progress heartbeat. Written by the worker via the internal
    # heartbeat endpoint; read by the frontend progress bar. ``phase``
    # is the coarse stage; ``progress_pct`` is a 0-100 float clamped to
    # an int column (storing as float adds no UX value).
    progress_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    phase: Mapped[str | None] = mapped_column(String(32), nullable=True)

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


@final
class BlurExport(Base, UUIDMixin, TimestampMixin):
    """One user-requested NLE-compatible layer export of a parent
    :class:`BlurJob`.

    An export takes a done blur job + a subset of its per-category
    masks and composites a ProRes 4444 ``.mov`` with alpha only on the
    selected blur regions. The parent's ``mask_s3_keys`` is the source
    of truth for what masks exist; ``categories`` here is the subset
    the customer asked for at export-request time. Immutable once
    persisted — changing the category set = a new export row.

    Loose coupling: blur_exports holds a FK on ``blur_jobs.id`` but the
    export worker never touches ``BlurJob`` directly. It only reads
    what the export row's claim endpoint hands out (layer source keys
    resolved server-side).
    """

    __tablename__ = "blur_exports"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blur_job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("blur_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=BLUR_STATUS_QUEUED,
    )
    # JSONB list of BlurCategory strings the customer selected. Kept as
    # JSONB (not array of enum) so the Postgres schema stays blur-side
    # and never depends on a pg ENUM that would have to evolve lockstep
    # with the contracts BlurCategory literal.
    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    categories_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)

    layer_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    lease_token: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__: tuple[object, ...] = (
        Index("ix_blur_exports_org_requested", "org_id", "requested_at"),
        Index(
            "ix_blur_exports_active",
            "org_id", "status",
            postgresql_where=(status.in_([BLUR_STATUS_QUEUED, BLUR_STATUS_RUNNING])),
        ),
        Index(
            "ix_blur_exports_dedupe",
            "blur_job_id", "categories_hash", "format", "requested_at",
        ),
    )
