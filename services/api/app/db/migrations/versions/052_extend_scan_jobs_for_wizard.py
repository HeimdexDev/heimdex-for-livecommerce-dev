"""Extend product_scan_jobs for the 4-step wizard (Phase 4 foundation)

Adds the parent-child orchestration columns + the new ``mode`` discriminator
that supersedes the ``catalog_entry_id IS NULL`` heuristic. Adds three new
stage ENUM values (``preview_ready``, ``fanned_out``, ``committed``) for the
scan-order lifecycle. Adds CHECK constraints and partial indexes that drive
idempotency lookups, the per-replica child-runner poll, and parent-only
concurrency counting.

No new tables. The parent-child relationship lives entirely in
``product_scan_jobs`` rows linked by ``parent_job_id``.

Existing rows are backfilled to ``mode='enumerate'`` — both the enumeration
flow and the legacy single-product flow (``enqueue_clip``) map to
``mode='enumerate'``; the dispatch path additionally branches on
``catalog_entry_id IS NULL`` for the enumerate-vs-legacy-tracking distinction
during the +4wk ``enqueue_clip`` deprecation window.

Plan: ``.claude/plans/shorts-auto-product-v2-phase-4-7.md`` §3.

Revision ID: 052_extend_scan_jobs_for_wizard
Revises: 051_create_product_catalog
Create Date: 2026-05-02

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "052_extend_scan_jobs_for_wizard"
down_revision: str | None = "051_create_product_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extend the product_scan_stage ENUM with three new values.
    #
    # PostgreSQL 12+ allows ``ALTER TYPE ADD VALUE`` inside a transaction
    # but the new value cannot be used in the same transaction. We don't
    # INSERT any rows with these new values here; downstream service-layer
    # code does that.
    #
    # ``IF NOT EXISTS`` makes the migration idempotent on re-runs.
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TYPE product_scan_stage ADD VALUE IF NOT EXISTS 'preview_ready'"
    )
    op.execute(
        "ALTER TYPE product_scan_stage ADD VALUE IF NOT EXISTS 'fanned_out'"
    )
    op.execute(
        "ALTER TYPE product_scan_stage ADD VALUE IF NOT EXISTS 'committed'"
    )

    # ------------------------------------------------------------------
    # 2. Add the new columns to product_scan_jobs.
    #
    # ``mode`` defaults to 'enumerate' so existing rows are atomically
    # backfilled. The dispatch path uses (mode, catalog_entry_id) jointly
    # during the legacy-tracking deprecation window:
    #
    #   mode='enumerate' AND catalog_entry_id IS NULL  → enumeration job
    #   mode='enumerate' AND catalog_entry_id NOT NULL → legacy single-
    #                                                    product tracking
    #                                                    (deprecated)
    #   mode='scan_order'                              → wizard parent
    #   mode='render_child'                            → wizard child
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD COLUMN parent_job_id UUID NULL
                REFERENCES product_scan_jobs(id) ON DELETE SET NULL,
            ADD COLUMN mode TEXT NOT NULL DEFAULT 'enumerate',
            ADD COLUMN requested_count INTEGER NULL,
            ADD COLUMN length_seconds INTEGER NULL,
            ADD COLUMN time_range_start_ms INTEGER NULL,
            ADD COLUMN time_range_end_ms INTEGER NULL,
            ADD COLUMN product_distribution TEXT NULL,
            ADD COLUMN language TEXT NULL,
            ADD COLUMN shorts_index INTEGER NULL,
            ADD COLUMN intent TEXT NULL,
            ADD COLUMN settings_hash TEXT NULL
    """)

    # ------------------------------------------------------------------
    # 3. CHECK constraints — every constraint mirrors the SQLAlchemy
    # ``CheckConstraint`` in ``models.py`` so ``alembic --autogenerate``
    # does not propose redundant DROP/CREATE pairs on a future revision.
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_mode
            CHECK (mode IN ('enumerate', 'scan_order', 'render_child'))
    """)
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_distribution
            CHECK (
                product_distribution IS NULL
                OR product_distribution IN ('single', 'multi')
            )
    """)
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_language
            CHECK (language IS NULL OR language IN ('ko', 'en'))
    """)
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_intent
            CHECK (intent IS NULL OR intent IN ('preview', 'commit'))
    """)
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_parent_child
            CHECK (
                (mode = 'render_child' AND parent_job_id IS NOT NULL
                                       AND shorts_index IS NOT NULL)
                OR (mode <> 'render_child' AND parent_job_id IS NULL
                                            AND shorts_index IS NULL)
            )
    """)
    # Q4 (codex pushback): scan_order parents must NEVER carry render_job_id;
    # children own renders. Docstring alone wasn't sufficient — DB enforces it.
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_parent_no_render
            CHECK (mode <> 'scan_order' OR render_job_id IS NULL)
    """)
    # scan_order parents MUST carry settings_hash + intent; everyone else MUST NOT.
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_parent_required_fields
            CHECK (
                (mode = 'scan_order'
                    AND settings_hash IS NOT NULL
                    AND intent IS NOT NULL)
                OR (mode <> 'scan_order'
                    AND settings_hash IS NULL
                    AND intent IS NULL)
            )
    """)
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_time_range
            CHECK (
                (time_range_start_ms IS NULL AND time_range_end_ms IS NULL)
                OR (time_range_end_ms > time_range_start_ms)
            )
    """)
    # Q5 (codex-revised): tightened from 5..600 to 10..120 seconds. Multi-
    # product picker calibration past 120s is unproven; deferred to Phase 7.
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_length
            CHECK (
                length_seconds IS NULL
                OR (length_seconds >= 10 AND length_seconds <= 120)
            )
    """)
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_count
            CHECK (
                requested_count IS NULL
                OR (requested_count >= 1 AND requested_count <= 50)
            )
    """)
    # Q5 aggregate cap: count * length <= 1800s (30 min total per scan order).
    # Codex caught: my original budget rationale was wrong — the daily cost
    # ledger tracks SCAN cost (heartbeat/complete/fail), not FFmpeg render
    # cost. This aggregate cap is the right guard against runaway output.
    op.execute("""
        ALTER TABLE product_scan_jobs
            ADD CONSTRAINT ck_psj_aggregate_output
            CHECK (
                requested_count IS NULL
                OR length_seconds IS NULL
                OR (requested_count * length_seconds <= 1800)
            )
    """)

    # ------------------------------------------------------------------
    # 4. Indexes — replace the existing active-only index so it counts
    # parents only, then add three new partial indexes for the wizard's
    # hot-path queries.
    # ------------------------------------------------------------------

    # NOTE: ``ix_product_scan_jobs_active`` rebuild moved to migration
    # ``053_recreate_active_index_with_wizard_stages`` because Postgres
    # rejects using ``ALTER TYPE … ADD VALUE``-added enum members in
    # the same transaction that added them — the partial index's
    # ``WHERE stage IN ('preview_ready','fanned_out',…)`` predicate
    # tripped that restriction during initial deploys
    # (UnsafeNewEnumValueUsage). Splitting it lets the next migration
    # see the new enum values as committed members of the type.
    #
    # The OLD ix_product_scan_jobs_active (scoped to original active
    # stages, no mode filter) stays in place until 053 runs — fine
    # because the wizard concurrency cap doesn't trip until parents
    # actually start landing in the new stages.

    # Parent → children lookup. Used by GET /scan-orders/{parent_id} and
    # by cancel-cascade.
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_parent
            ON product_scan_jobs(parent_job_id)
            WHERE parent_job_id IS NOT NULL
    """)

    # Q3 (codex-revised): idempotency lookup on (org_id, user_id,
    # settings_hash, created_at). The defensive org_id fix in
    # ``ProductScanJobRepository.find_recent_duplicate`` requires this index
    # to keep the dedupe lookup O(log n) under load.
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_settings_hash
            ON product_scan_jobs(
                org_id, requested_by_user_id, settings_hash, created_at
            )
            WHERE mode = 'scan_order' AND settings_hash IS NOT NULL
    """)

    # Q1 (codex-revised): the child-runner asyncio loop polls for queued
    # render_child rows. This partial index keeps the poll O(1) at table
    # scale while the typical row count of queued children stays small.
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_child_queue
            ON product_scan_jobs(created_at)
            WHERE mode = 'render_child' AND stage = 'queued'
    """)


def downgrade() -> None:
    # Indexes — only the ones this migration created. The
    # ``ix_product_scan_jobs_active`` rebuild lives in migration 053
    # and is reverted there (running ``alembic downgrade -1`` from 053
    # restores the pre-053 active-index shape, then ``-1`` again from
    # 052 leaves the schema as it was at 051).
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_child_queue")
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_settings_hash")
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_parent")

    # Constraints (drop in reverse-add order; IF EXISTS for idempotency)
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_aggregate_output"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_count"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_length"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_time_range"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_parent_required_fields"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_parent_no_render"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_parent_child"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_intent"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_language"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_distribution"
    )
    op.execute(
        "ALTER TABLE product_scan_jobs "
        "DROP CONSTRAINT IF EXISTS ck_psj_mode"
    )

    # Columns (drop in reverse-add order)
    op.execute("""
        ALTER TABLE product_scan_jobs
            DROP COLUMN IF EXISTS settings_hash,
            DROP COLUMN IF EXISTS intent,
            DROP COLUMN IF EXISTS shorts_index,
            DROP COLUMN IF EXISTS language,
            DROP COLUMN IF EXISTS product_distribution,
            DROP COLUMN IF EXISTS time_range_end_ms,
            DROP COLUMN IF EXISTS time_range_start_ms,
            DROP COLUMN IF EXISTS length_seconds,
            DROP COLUMN IF EXISTS requested_count,
            DROP COLUMN IF EXISTS mode,
            DROP COLUMN IF EXISTS parent_job_id
    """)

    # Note: PostgreSQL ENUM values cannot be dropped (no
    # ``ALTER TYPE … DROP VALUE``). The new ``preview_ready`` /
    # ``fanned_out`` / ``committed`` literals stay in the type definition
    # post-downgrade. This is acceptable because:
    #   1. Downgrades on production schemas are rare and operator-driven.
    #   2. The orphaned values are harmless — no app code references them
    #      once the columns + dispatch are reverted.
    # If a true clean rollback is needed, follow PG's documented dance of
    # creating a new type + casting affected columns.