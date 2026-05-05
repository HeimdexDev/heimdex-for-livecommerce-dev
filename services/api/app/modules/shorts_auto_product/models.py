"""SQLAlchemy models for shorts-auto product mode v2.

Mirrors migration 051_create_product_catalog. Field-for-field
correspondence; do not drift without a migration update.

Three core tables + a daily-cost ledger:

* :class:`ProductCatalogEntry` — one distinct product detected in a
  video (lazy, populated on first user click). Per-video v1.
* :class:`ProductAppearance` — one qualifying appearance window for a
  ``(catalog_entry, scene)``. Frame-level bbox track lives in S3.
* :class:`ProductScanJob` — async job state machine. ``catalog_entry_id``
  ``NULL`` = enumeration job; non-null = tracking + assembly job.
* :class:`ProductScanDailyCost` — per-org-per-day running cost for
  the budget cap. Separate bucket from auto_shorts_llm /
  image_caption / video_summary.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, final
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy import Date as SADate
from sqlalchemy.dialects.postgresql import ARRAY, REAL
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base, TimestampMixin, UUIDMixin


# ---------- product_scan_jobs.stage ENUM ----------
#
# Created in raw SQL by migration 051. ``create_type=False`` tells
# SQLAlchemy not to attempt a re-create — the migration owns the type.
# Keep these literals in lockstep with:
#   * migration 051's ``CREATE TYPE product_scan_stage AS ENUM (...)``
#   * heimdex_media_contracts.product.ProductScanStage Literal
#   * heimdex_media_contracts.product.ALLOWED_SCAN_STAGES frozenset
SCAN_STAGE_QUEUED = "queued"
SCAN_STAGE_ENUMERATING = "enumerating"
SCAN_STAGE_ENUMERATION_DONE = "enumeration_done"
SCAN_STAGE_TRACKING = "tracking"
SCAN_STAGE_ASSEMBLING = "assembling"
SCAN_STAGE_RENDERING = "rendering"
# Phase 4 wizard stages — added in migration 052 via ALTER TYPE ADD VALUE.
SCAN_STAGE_PREVIEW_READY = "preview_ready"   # parent waiting on user commit (Phase 6)
SCAN_STAGE_FANNED_OUT = "fanned_out"         # parent waiting on N children to terminate
SCAN_STAGE_COMMITTED = "committed"           # parent terminal once all children terminate
SCAN_STAGE_DONE = "done"
SCAN_STAGE_FAILED = "failed"
SCAN_STAGE_CANCELLED = "cancelled"

ALL_SCAN_STAGES: tuple[str, ...] = (
    SCAN_STAGE_QUEUED,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_ENUMERATION_DONE,
    SCAN_STAGE_TRACKING,
    SCAN_STAGE_ASSEMBLING,
    SCAN_STAGE_RENDERING,
    SCAN_STAGE_PREVIEW_READY,
    SCAN_STAGE_FANNED_OUT,
    SCAN_STAGE_COMMITTED,
    SCAN_STAGE_DONE,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_CANCELLED,
)

# Stages where the job is still in-flight — drives the per-org
# concurrency cap query (``ix_product_scan_jobs_active``). Parents in
# ``preview_ready`` and ``fanned_out`` still hold an active slot; children
# (``mode='render_child'``) are excluded from the count via the index's
# WHERE clause.
ACTIVE_SCAN_STAGES: frozenset[str] = frozenset({
    SCAN_STAGE_QUEUED,
    SCAN_STAGE_ENUMERATING,
    SCAN_STAGE_TRACKING,
    SCAN_STAGE_ASSEMBLING,
    SCAN_STAGE_RENDERING,
    SCAN_STAGE_PREVIEW_READY,
    SCAN_STAGE_FANNED_OUT,
})

TERMINAL_SCAN_STAGES: frozenset[str] = frozenset({
    SCAN_STAGE_DONE,
    SCAN_STAGE_COMMITTED,
    SCAN_STAGE_FAILED,
    SCAN_STAGE_CANCELLED,
})


# ---------- product_scan_jobs.mode discriminator (Phase 4) ----------
#
# Replaces the ``catalog_entry_id IS NULL`` heuristic that pre-dated the
# 4-step wizard. The dispatch path branches:
#
#   mode='enumerate' AND catalog_entry_id IS NULL  → enumeration job
#   mode='enumerate' AND catalog_entry_id NOT NULL → legacy single-product
#                                                    tracking (deprecated;
#                                                    +4wk sunset window)
#   mode='scan_order'                              → wizard parent
#   mode='render_child'                            → wizard child
SCAN_MODE_ENUMERATE = "enumerate"
SCAN_MODE_SCAN_ORDER = "scan_order"
SCAN_MODE_RENDER_CHILD = "render_child"

ALL_SCAN_MODES: tuple[str, ...] = (
    SCAN_MODE_ENUMERATE,
    SCAN_MODE_SCAN_ORDER,
    SCAN_MODE_RENDER_CHILD,
)

# Wizard intent (parent only) — separates preview-flow dedupe from
# commit-flow dedupe in the ``settings_hash`` keyspace.
SCAN_INTENT_PREVIEW = "preview"
SCAN_INTENT_COMMIT = "commit"

ALL_SCAN_INTENTS: tuple[str, ...] = (SCAN_INTENT_PREVIEW, SCAN_INTENT_COMMIT)

# Product distribution mode (parent only) — drives picker selection.
PRODUCT_DISTRIBUTION_SINGLE = "single"
PRODUCT_DISTRIBUTION_MULTI = "multi"

ALL_PRODUCT_DISTRIBUTIONS: tuple[str, ...] = (
    PRODUCT_DISTRIBUTION_SINGLE,
    PRODUCT_DISTRIBUTION_MULTI,
)

# Wizard language (parent only).
LANGUAGE_KO = "ko"
LANGUAGE_EN = "en"

ALL_LANGUAGES: tuple[str, ...] = (LANGUAGE_KO, LANGUAGE_EN)

# SQLAlchemy enum type bound to the existing Postgres ENUM. All ORM
# reads / writes go through this so type-safety is preserved.
PRODUCT_SCAN_STAGE_ENUM = SAEnum(
    *ALL_SCAN_STAGES,
    name="product_scan_stage",
    create_type=False,
    native_enum=True,
    validate_strings=True,
)


# ---------- ProductCatalogEntry ----------

@final
class ProductCatalogEntry(Base, UUIDMixin, TimestampMixin):
    """One distinct product detected in a video.

    Populated lazily by ``product-enumerate-worker`` on first user
    click. ``rejected_at`` is a soft delete — rejected rows are kept
    for threshold tuning so we can re-classify without re-running
    enumeration.
    """

    __tablename__ = "product_catalog_entries"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Best reference frame — vision-source rows have a canonical crop
    # picked by the reference picker's quality composite. STT-source
    # rows have NULL for every canonical_* field (the transcript pass
    # never sees a frame). Migration 055 dropped NOT NULL on these
    # columns so STT-source rows can be inserted without sentinels.
    canonical_crop_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_video_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    canonical_frame_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical_bbox_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical_bbox_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical_bbox_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    canonical_bbox_h: Mapped[int | None] = mapped_column(Integer, nullable=True)

    llm_label: Mapped[str] = mapped_column(Text, nullable=False)
    user_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 768-dim matches google/siglip2-base-patch16-256 deployed in
    # drive-visual-embed-worker. Bumping this dim is a coordinated
    # migration across both workers and OS — never change in isolation.
    siglip2_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768), nullable=True,
    )

    enumeration_confidence: Mapped[float] = mapped_column(REAL, nullable=False)

    # Vision-only — bbox-area / clarity composite. NULL for STT-source
    # rows (no visual signal). Migration 055 dropped the NOT NULL.
    prominence_score: Mapped[float | None] = mapped_column(REAL, nullable=True)

    enumeration_version: Mapped[str] = mapped_column(Text, nullable=False)
    enumeration_prompt_version: Mapped[str] = mapped_column(Text, nullable=False)

    # ---------- v0.15.0 — STT-pivot spoken-form aliases (migration 054) ----------
    #
    # Search-only metadata used by the ``shorts_auto_product`` STT track
    # (see ``.claude/plans/shorts-auto-product-stt-pivot.md`` PR 1b).
    # Populated post-hoc by the API via ``app.cli.backfill_spoken_aliases``
    # — NOT by the enumerate worker. Backward-compat with v0.14.0
    # workers: they produce ``ProductCatalogEntry`` payloads without
    # this field, the v0.15.0 contracts schema applies the empty-list
    # default on parse, the DB column accepts the empty default.
    #
    # ``aliases_generated_at`` IS NULL means "never attempted"; the
    # backfill CLI selection query keys on it. The provenance pair
    # (timestamp + prompt version) lets a future prompt bump target
    # only stale rows for re-generation without disturbing the
    # already-shipped enumeration calibration gates.
    spoken_aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}",
    )
    aliases_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    aliases_prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---------- v0.16.0 — STT-first enumeration (migration 055) ----------
    #
    # Provenance flag for the enumeration path that produced this row.
    # CHECK-locked at the DB level to {vision, stt, stt_xref, manifest,
    # hybrid}; do NOT add a new value without updating both the
    # migration's CHECK constraint AND the wizard UI's badge mapping.
    # ``server_default='vision'`` makes existing rows inherit the
    # correct provenance without a backfill — pre-PR-2 catalog was
    # 100% vision-enumerated.
    #
    # ``first_mention_ms`` and ``example_quote`` are STT-source-only;
    # NULL on vision rows. ``first_mention_ms`` orders the wizard's
    # catalog view chronologically (Phase 4 wizard UX) and anchors
    # optional Phase 5 visual back-fill. ``example_quote`` powers the
    # provenance tooltip on STT-source cards.
    enumeration_source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="vision",
    )
    first_mention_ms: Mapped[int | None] = mapped_column(
        # BIGINT — videos can run hours; INT4 would overflow at ~24 days
        # but the safe pattern across the codebase is BIGINT for any
        # millisecond timestamp.
        BigInteger, nullable=True,
    )
    example_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__: tuple[Any, ...] = (
        # Active-only index for the gallery view query.
        Index(
            "ix_product_catalog_org_video",
            "org_id", "video_id",
            postgresql_where=(rejected_at.is_(None)),
        ),
        # Cross-video kNN (v2 prep — populated from day one).
        Index(
            "ix_product_catalog_siglip2",
            "siglip2_embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"siglip2_embedding": "vector_cosine_ops"},
        ),
    )


# ---------- ProductAppearance ----------

@final
class ProductAppearance(Base, UUIDMixin):
    """One contiguous appearance window for a catalog entry.

    Note: no ``updated_at`` — appearances are append-only per scan.
    Re-running tracking on the same catalog entry inserts a new batch
    keyed by ``tracker_version``; old rows stay until explicitly purged.
    """

    __tablename__ = "product_appearances"

    catalog_entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_catalog_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalized for the multi-tenant guard — querying appearances
    # by id alone would otherwise need a join to validate ownership.
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )

    # OpenSearch ``scene_id`` (no org prefix); join via
    # ``f"{org_id}:{scene_id}"`` per existing convention.
    scene_id: Mapped[str] = mapped_column(Text, nullable=False)
    window_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    window_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    avg_bbox_area_pct: Mapped[float] = mapped_column(REAL, nullable=False)
    avg_confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    has_narration_mention: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    has_ocr_overlap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    co_appearing_catalog_entry_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)),
        nullable=False,
        server_default="{}",
    )

    # Frame-level bbox track lives in S3, never in Postgres — at 5fps
    # over 60 minutes that's 18k rows per appearance, which is far
    # cheaper to scan as a gzipped blob than as relational rows.
    raw_bbox_track_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    tracker_version: Mapped[str] = mapped_column(Text, nullable=False)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__: tuple[Any, ...] = (
        # Active-only — driven by the `rejected_reason IS NULL` partial
        # index in the migration. Speeds up the common "give me the
        # qualifying appearances for this product" query.
        Index(
            "ix_product_appearances_catalog",
            "catalog_entry_id",
            postgresql_where=(rejected_reason.is_(None)),
        ),
        Index("ix_product_appearances_org", "org_id"),
        # Mirrors the migration's CHECK — kept here so SQLAlchemy
        # autogenerate doesn't try to drop / recreate it on next
        # alembic revision --autogenerate.
        CheckConstraint(
            "window_end_ms > window_start_ms",
            name="ck_product_appearances_window_order",
        ),
    )


# ---------- ProductScanJob ----------

@final
class ProductScanJob(Base, UUIDMixin):
    """Async job state machine for shorts-auto product mode v2.

    Job kind is discriminated by ``mode`` (Phase 4) — NOT by
    ``catalog_entry_id`` (the pre-Phase-4 heuristic). The dispatch path
    must branch on ``mode``:

    * ``mode='enumerate'`` AND ``catalog_entry_id IS NULL`` →
      enumeration job (output: ``catalog_entries`` populated).
    * ``mode='enumerate'`` AND ``catalog_entry_id IS NOT NULL`` →
      legacy single-product tracking (deprecated; ``enqueue_clip``
      sunsets after the +4wk window post-Phase-4 ship).
    * ``mode='scan_order'`` (parent) → wizard submission. Holds wizard
      criteria (``length_seconds``, ``time_range_*``, ``requested_count``,
      ``product_distribution``, ``language``, ``intent``,
      ``settings_hash``). GPU pipeline runs ONCE for the whole catalog;
      ``render_job_id`` is **always NULL** (DB-enforced via
      ``ck_psj_parent_no_render``) — children own renders.
    * ``mode='render_child'`` → one of N child jobs of a parent. Holds
      ``parent_job_id`` and ``shorts_index``. CPU-only — runs in the
      API process via the child runner loop in ``app.main:lifespan``.
      Each child enqueues exactly one ``ShortsRenderJob``.

    Worker lease pattern matches blur. Stale workers can never
    overwrite a re-claimed job because the ``/internal/products/*``
    callbacks check ``claimed_by`` against the row before mutating.
    """

    __tablename__ = "product_scan_jobs"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
    )
    video_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("drive_files.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Enumeration job vs tracking job.
    catalog_entry_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_catalog_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    duration_preset_sec: Mapped[int] = mapped_column(Integer, nullable=False)

    stage: Mapped[str] = mapped_column(
        PRODUCT_SCAN_STAGE_ENUM,
        nullable=False,
        server_default=SCAN_STAGE_QUEUED,
    )
    progress_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    progress_label: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Worker lease (mirrors blur).
    claimed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Render job FK — semantics are mode-aware:
    #   mode='enumerate' AND catalog_entry_id NOT NULL (legacy tracking)
    #     → set to the produced render_job_id
    #   mode='scan_order' (parent)
    #     → ALWAYS NULL (DB-enforced via ck_psj_parent_no_render); children
    #       own their own render jobs. Querying parents → render via this
    #       FK is incorrect post-Phase-4.
    #   mode='render_child'
    #     → set to the child's produced render_job_id
    render_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("shorts_render_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Running cost tally — workers add to this on every heartbeat so
    # the cap-check remains O(1) instead of summing job rows.
    cost_usd_estimate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0",
    )

    # ---------- Phase 4 wizard fields (migration 052) ----------
    #
    # Parent → children relationship lives entirely in this table. The
    # ck_psj_parent_child constraint enforces:
    #   mode='render_child' → parent_job_id NOT NULL AND shorts_index NOT NULL
    #   mode != 'render_child' → parent_job_id NULL AND shorts_index NULL
    parent_job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("product_scan_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=SCAN_MODE_ENUMERATE,
    )
    requested_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    length_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_range_start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_range_end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_distribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    shorts_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 'preview' | 'commit' — separates wizard intent in settings_hash keyspace.
    # Required when mode='scan_order' (ck_psj_parent_required_fields), NULL
    # everywhere else.
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SHA256 of canonical-JSON wizard inputs (see service.compute_settings_hash).
    # Drives idempotency lookups via ix_product_scan_jobs_settings_hash.
    # Required when mode='scan_order', NULL everywhere else.
    settings_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__: tuple[Any, ...] = (
        Index("ix_product_scan_jobs_org_video", "org_id", "video_id"),
        Index(
            "ix_product_scan_jobs_user_recent",
            "requested_by_user_id", "created_at",
        ),
        # Active-only — drives the per-org concurrency cap. Mirrors the
        # ENUM list in ACTIVE_SCAN_STAGES; keep both in sync. Excludes
        # ``mode='render_child'`` so children don't take a slot — only
        # parents (and pre-Phase-4 enumerate / legacy tracking jobs)
        # count toward the cap.
        Index(
            "ix_product_scan_jobs_active",
            "org_id", "stage",
            postgresql_where=(
                stage.in_(list(ACTIVE_SCAN_STAGES))
                & (mode != SCAN_MODE_RENDER_CHILD)
            ),
        ),
        # Legacy idempotency lookup for the pre-Phase-4 60s scan-debounce
        # window (kept for ``find_recent_duplicate``'s legacy callers).
        Index(
            "ix_product_scan_jobs_idempotency",
            "video_id", "requested_by_user_id", "catalog_entry_id", "created_at",
        ),
        # Parent → children lookup. Used by GET /scan-orders/{parent_id}
        # and by cancel-cascade.
        Index(
            "ix_product_scan_jobs_parent",
            "parent_job_id",
            postgresql_where=(parent_job_id.is_not(None)),
        ),
        # Q3 (codex-revised): wizard idempotency lookup keyed on
        # (org_id, user_id, settings_hash, created_at). The matching
        # repository query (find_recent_scan_order_duplicate) MUST filter
        # on org_id — codex caught the original find_recent_duplicate
        # bug where org_id was missing.
        Index(
            "ix_product_scan_jobs_settings_hash",
            "org_id", "requested_by_user_id", "settings_hash", "created_at",
            postgresql_where=(
                (mode == SCAN_MODE_SCAN_ORDER) & settings_hash.is_not(None)
            ),
        ),
        # Q1 (codex-revised): the child-runner asyncio loop polls for
        # queued render_child rows. This partial index keeps the poll
        # O(1) at table scale while the typical row count of queued
        # children stays small.
        Index(
            "ix_product_scan_jobs_child_queue",
            "created_at",
            postgresql_where=(
                (mode == SCAN_MODE_RENDER_CHILD) & (stage == SCAN_STAGE_QUEUED)
            ),
        ),
        # Mirrors of CHECK constraints in migration 052. Keep these in
        # sync so ``alembic --autogenerate`` doesn't propose redundant
        # DROP/CREATE pairs on a future revision.
        CheckConstraint(
            "mode IN ('enumerate','scan_order','render_child')",
            name="ck_psj_mode",
        ),
        CheckConstraint(
            "product_distribution IS NULL OR product_distribution IN ('single','multi')",
            name="ck_psj_distribution",
        ),
        CheckConstraint(
            "language IS NULL OR language IN ('ko','en')",
            name="ck_psj_language",
        ),
        CheckConstraint(
            "intent IS NULL OR intent IN ('preview','commit')",
            name="ck_psj_intent",
        ),
        CheckConstraint(
            "(mode = 'render_child' AND parent_job_id IS NOT NULL "
            "AND shorts_index IS NOT NULL) "
            "OR (mode <> 'render_child' AND parent_job_id IS NULL "
            "AND shorts_index IS NULL)",
            name="ck_psj_parent_child",
        ),
        # Q4 (codex pushback): scan_order parents must NEVER carry
        # render_job_id; children own renders.
        CheckConstraint(
            "mode <> 'scan_order' OR render_job_id IS NULL",
            name="ck_psj_parent_no_render",
        ),
        CheckConstraint(
            "(mode = 'scan_order' AND settings_hash IS NOT NULL "
            "AND intent IS NOT NULL) "
            "OR (mode <> 'scan_order' AND settings_hash IS NULL "
            "AND intent IS NULL)",
            name="ck_psj_parent_required_fields",
        ),
        CheckConstraint(
            "(time_range_start_ms IS NULL AND time_range_end_ms IS NULL) "
            "OR (time_range_end_ms > time_range_start_ms)",
            name="ck_psj_time_range",
        ),
        # Q5 (codex-revised): tightened from 5..600 to 10..120 seconds.
        CheckConstraint(
            "length_seconds IS NULL "
            "OR (length_seconds >= 10 AND length_seconds <= 120)",
            name="ck_psj_length",
        ),
        CheckConstraint(
            "requested_count IS NULL "
            "OR (requested_count >= 1 AND requested_count <= 50)",
            name="ck_psj_count",
        ),
        # Q5 aggregate cap: count * length <= 1800s (30 min total
        # output per scan order). Codex caught: my original budget
        # rationale was wrong — the daily cost ledger tracks SCAN cost
        # (heartbeat/complete/fail), not FFmpeg render cost. This
        # aggregate cap is the right guard.
        CheckConstraint(
            "requested_count IS NULL "
            "OR length_seconds IS NULL "
            "OR (requested_count * length_seconds <= 1800)",
            name="ck_psj_aggregate_output",
        ),
    )


# ---------- ProductScanDailyCost ----------

@final
class ProductScanDailyCost(Base):
    """Per-org-per-day running cost for the v2 budget cap.

    Composite PK ``(org_id, day)`` — at most one row per org per UTC
    day. Workers and the API both update via ``ON CONFLICT … DO
    UPDATE`` so concurrent heartbeats don't lose increments.
    """

    __tablename__ = "product_scan_daily_costs"

    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    day: Mapped[date] = mapped_column(SADate, primary_key=True, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


__all__ = [
    "ACTIVE_SCAN_STAGES",
    "ALL_LANGUAGES",
    "ALL_PRODUCT_DISTRIBUTIONS",
    "ALL_SCAN_INTENTS",
    "ALL_SCAN_MODES",
    "ALL_SCAN_STAGES",
    "LANGUAGE_EN",
    "LANGUAGE_KO",
    "PRODUCT_DISTRIBUTION_MULTI",
    "PRODUCT_DISTRIBUTION_SINGLE",
    "PRODUCT_SCAN_STAGE_ENUM",
    "ProductAppearance",
    "ProductCatalogEntry",
    "ProductScanDailyCost",
    "ProductScanJob",
    "SCAN_INTENT_COMMIT",
    "SCAN_INTENT_PREVIEW",
    "SCAN_MODE_ENUMERATE",
    "SCAN_MODE_RENDER_CHILD",
    "SCAN_MODE_SCAN_ORDER",
    "SCAN_STAGE_ASSEMBLING",
    "SCAN_STAGE_CANCELLED",
    "SCAN_STAGE_COMMITTED",
    "SCAN_STAGE_DONE",
    "SCAN_STAGE_ENUMERATING",
    "SCAN_STAGE_ENUMERATION_DONE",
    "SCAN_STAGE_FAILED",
    "SCAN_STAGE_FANNED_OUT",
    "SCAN_STAGE_PREVIEW_READY",
    "SCAN_STAGE_QUEUED",
    "SCAN_STAGE_RENDERING",
    "SCAN_STAGE_TRACKING",
    "TERMINAL_SCAN_STAGES",
]
