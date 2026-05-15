"""Create product catalog tables for shorts-auto product mode v2

Lazy per-video product catalog populated on user click (no precompute
at ingest). Three core tables plus a daily-cost ledger:

* ``product_catalog_entries``  — one row per distinct product detected
  in a video. Populated by the enumerate worker. Carries a 768-dim
  SigLIP2 embedding (variant: google/siglip2-base-patch16-256, must
  match drive-visual-embed-worker exactly so existing scene-level OS
  embeddings can serve as the coarse pre-filter for tracking).
* ``product_appearances`` — one row per qualifying appearance window
  for a (catalog_entry, scene). Populated by the track worker.
  Frame-level bbox tracks live in S3 keyed by raw_bbox_track_s3_key —
  Postgres never stores per-frame data.
* ``product_scan_jobs`` — async job state machine driving the cold-
  start UX. Mirrors the blur lease/heartbeat pattern. ``catalog_entry_id``
  null = enumeration job; non-null = tracking + assembly job.
* ``product_scan_daily_costs`` — per-org-per-day running cost. Separate
  budget bucket from auto_shorts_llm / image_caption / video_summary.

Plan: ``.claude/plans/shorts-auto-product-v2.md`` — every column maps
back to a section there. Decision log at §15.

Revision ID: 051_create_product_catalog
Revises: 050_create_subtitle_presets
Create Date: 2026-04-29

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "051_create_product_catalog"
down_revision: str | None = "050_create_subtitle_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector is already enabled by migration 023; the IF NOT EXISTS
    # guard makes the migration safe on environments where 023 may have
    # been replaced by a different bootstrap path.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # product_catalog_entries
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE product_catalog_entries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            video_id UUID NOT NULL REFERENCES drive_files(id) ON DELETE CASCADE,

            canonical_crop_s3_key TEXT NOT NULL,
            canonical_video_id UUID NOT NULL,
            canonical_frame_idx INTEGER NOT NULL CHECK (canonical_frame_idx >= 0),
            canonical_bbox_x INTEGER NOT NULL CHECK (canonical_bbox_x >= 0),
            canonical_bbox_y INTEGER NOT NULL CHECK (canonical_bbox_y >= 0),
            canonical_bbox_w INTEGER NOT NULL CHECK (canonical_bbox_w > 0),
            canonical_bbox_h INTEGER NOT NULL CHECK (canonical_bbox_h > 0),

            llm_label TEXT NOT NULL,
            user_label TEXT,

            -- 768-dim matches google/siglip2-base-patch16-256 deployed in
            -- drive-visual-embed-worker. Bumping this dimension is a
            -- coordinated migration with the visual-embed-worker; do NOT
            -- change in isolation.
            siglip2_embedding vector(768),

            enumeration_confidence REAL NOT NULL
                CHECK (enumeration_confidence BETWEEN 0 AND 1),
            prominence_score REAL NOT NULL
                CHECK (prominence_score BETWEEN 0 AND 1),

            enumeration_version TEXT NOT NULL,
            enumeration_prompt_version TEXT NOT NULL,

            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            rejected_at TIMESTAMPTZ,
            rejected_reason TEXT
        )
    """)
    op.execute(
        "COMMENT ON TABLE product_catalog_entries IS "
        "'Per-video product catalog populated lazily by product-enumerate-worker. "
        "Per-video v1; cross-video matching is v2.'"
    )

    # Active-only index — cheap (org, video) lookup for the gallery view.
    op.execute("""
        CREATE INDEX ix_product_catalog_org_video
            ON product_catalog_entries (org_id, video_id)
            WHERE rejected_at IS NULL
    """)
    # Cross-video kNN search (v2 prep — populated from day one so v2
    # has data ready). lists=100 matches the face_identities pattern.
    op.execute("""
        CREATE INDEX ix_product_catalog_siglip2
            ON product_catalog_entries USING ivfflat
            (siglip2_embedding vector_cosine_ops)
            WITH (lists = 100)
    """)

    # ------------------------------------------------------------------
    # product_appearances
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE product_appearances (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            catalog_entry_id UUID NOT NULL
                REFERENCES product_catalog_entries(id) ON DELETE CASCADE,
            -- denormalized for tenant guard on direct-by-id queries
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,

            -- OpenSearch scene_id (no org_id prefix); join to OS via
            -- f'{org_id}:{scene_id}' per existing convention.
            scene_id TEXT NOT NULL,
            window_start_ms INTEGER NOT NULL CHECK (window_start_ms >= 0),
            window_end_ms INTEGER NOT NULL CHECK (window_end_ms > 0),

            avg_bbox_area_pct REAL NOT NULL
                CHECK (avg_bbox_area_pct BETWEEN 0 AND 1),
            avg_confidence REAL NOT NULL
                CHECK (avg_confidence BETWEEN 0 AND 1),
            has_narration_mention BOOLEAN NOT NULL DEFAULT false,
            has_ocr_overlap BOOLEAN NOT NULL DEFAULT false,
            co_appearing_catalog_entry_ids UUID[] NOT NULL DEFAULT '{}',

            -- Frame-level bbox track lives in S3, never in Postgres.
            raw_bbox_track_s3_key TEXT,

            tracker_version TEXT NOT NULL,
            rejected_reason TEXT,

            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT ck_product_appearances_window_order
                CHECK (window_end_ms > window_start_ms)
        )
    """)
    op.execute(
        "COMMENT ON TABLE product_appearances IS "
        "'Per-product appearance windows. Populated by product-track-worker. "
        "rejected_reason rows are kept for threshold tuning without re-running tracking.'"
    )
    op.execute("""
        CREATE INDEX ix_product_appearances_catalog
            ON product_appearances (catalog_entry_id)
            WHERE rejected_reason IS NULL
    """)
    op.execute("""
        CREATE INDEX ix_product_appearances_org
            ON product_appearances (org_id)
    """)

    # ------------------------------------------------------------------
    # product_scan_jobs
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE product_scan_stage AS ENUM (
            'queued',
            'enumerating',
            'enumeration_done',
            'tracking',
            'assembling',
            'rendering',
            'done',
            'failed',
            'cancelled'
        )
    """)
    op.execute("""
        CREATE TABLE product_scan_jobs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            video_id UUID NOT NULL REFERENCES drive_files(id) ON DELETE CASCADE,
            requested_by_user_id UUID NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,

            -- enum job vs track job: NULL catalog_entry_id = enumeration.
            catalog_entry_id UUID REFERENCES product_catalog_entries(id)
                ON DELETE SET NULL,
            duration_preset_sec INTEGER NOT NULL
                CHECK (duration_preset_sec IN (30, 60, 90)),

            stage product_scan_stage NOT NULL DEFAULT 'queued',
            progress_pct INTEGER NOT NULL DEFAULT 0
                CHECK (progress_pct BETWEEN 0 AND 100),
            progress_label TEXT,

            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            failed_at TIMESTAMPTZ,
            error_message TEXT,
            error_code TEXT,

            -- Worker lease (matches blur pattern)
            claimed_by TEXT,
            claimed_at TIMESTAMPTZ,
            lease_expires_at TIMESTAMPTZ,
            last_heartbeat_at TIMESTAMPTZ,

            -- Output of tracking jobs
            render_job_id UUID REFERENCES shorts_render_jobs(id)
                ON DELETE SET NULL,

            -- Running cost tally; O(1) lookup for cap checks
            cost_usd_estimate NUMERIC(10, 4) NOT NULL DEFAULT 0,

            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "COMMENT ON TABLE product_scan_jobs IS "
        "'Async job state machine for shorts-auto product v2. "
        "NULL catalog_entry_id = enumeration job; non-null = track + assembly.'"
    )
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_org_video
            ON product_scan_jobs (org_id, video_id)
    """)
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_user_recent
            ON product_scan_jobs (requested_by_user_id, created_at DESC)
    """)
    # Active-job index — drives the per-org concurrency cap query.
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_active
            ON product_scan_jobs (org_id, stage)
            WHERE stage IN ('queued','enumerating','tracking','assembling','rendering')
    """)
    # Idempotency lookup for the 60s scan-debounce window.
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_idempotency
            ON product_scan_jobs
            (video_id, requested_by_user_id, catalog_entry_id, created_at DESC)
    """)

    # ------------------------------------------------------------------
    # product_scan_daily_costs
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE product_scan_daily_costs (
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            day DATE NOT NULL,
            cost_usd NUMERIC(10, 4) NOT NULL DEFAULT 0
                CHECK (cost_usd >= 0),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, day)
        )
    """)
    op.execute(
        "COMMENT ON TABLE product_scan_daily_costs IS "
        "'Per-org-per-day running cost for shorts-auto product v2. Separate budget "
        "bucket from auto_shorts_llm / image_caption / video_summary. "
        "Hard cap default $50/day/org; 80%% triggers Slack warn.'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_scan_daily_costs")
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_idempotency")
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_active")
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_user_recent")
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_org_video")
    op.execute("DROP TABLE IF EXISTS product_scan_jobs")
    op.execute("DROP TYPE IF EXISTS product_scan_stage")
    op.execute("DROP INDEX IF EXISTS ix_product_appearances_org")
    op.execute("DROP INDEX IF EXISTS ix_product_appearances_catalog")
    op.execute("DROP TABLE IF EXISTS product_appearances")
    op.execute("DROP INDEX IF EXISTS ix_product_catalog_siglip2")
    op.execute("DROP INDEX IF EXISTS ix_product_catalog_org_video")
    op.execute("DROP TABLE IF EXISTS product_catalog_entries")
    # Do NOT drop the ``vector`` extension — other tables (face_identities,
    # face_exemplars, scenes vector embeddings) depend on it.
