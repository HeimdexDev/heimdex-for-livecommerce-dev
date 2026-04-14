"""Add blur mask/progress columns + blur_exports table for layer export

Revision ID: 048_add_blur_masks_and_exports
Revises: 047_add_blur_jobs_table
Create Date: 2026-04-15

Extends the v0.9 blur subsystem to support the NLE-compatible layer
export workflow:

* ``blur_jobs`` gains three columns:
    - ``mask_s3_keys`` JSONB (nullable) — per-category FFV1 mask paths
      written by the pipeline and uploaded by drive-blur-worker
    - ``progress_pct`` INT (default 0) — 0-100 heartbeat from the
      pipeline, powers the live progress bar on the blur detail page
    - ``phase`` VARCHAR(32) (nullable) — coarse state within a running
      job: queued|initializing|detecting|encoding|uploading|finalizing
* ``blur_exports`` is a NEW table, one row per user-requested export.
  Scoped to a parent ``blur_jobs.id``, dedupe on
  ``(blur_job_id, categories_hash, format)``. Layer output lives at
  ``blur_exports/{video_id}/{export_id}/layer.mov`` and is reaped
  after 7 days by the S3 lifecycle rule (added in a separate infra PR).

Both halves are additive. No existing rows are touched; the column
backfills default to NULL / 0. Safe to roll back — ``blur_export_enabled``
stays ``false`` globally until an operator flips it per env.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "048_add_blur_masks_and_exports"
down_revision: str | None = "047_add_blur_jobs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- blur_jobs: masks + live progress ----------
    op.add_column(
        "blur_jobs",
        sa.Column("mask_s3_keys", JSONB, nullable=True),
    )
    op.add_column(
        "blur_jobs",
        sa.Column(
            "progress_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "blur_jobs",
        sa.Column("phase", sa.String(32), nullable=True),
    )

    # ---------- blur_exports ----------
    _ = op.create_table(
        "blur_exports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("blur_job_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("video_id", sa.String(255), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("categories", JSONB, nullable=False),
        sa.Column("categories_hash", sa.String(64), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("layer_s3_key", sa.String(512), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blur_exports")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"],
            name=op.f("fk_blur_exports_org_id_orgs"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blur_job_id"], ["blur_jobs.id"],
            name=op.f("fk_blur_exports_blur_job_id_blur_jobs"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["drive_files.id"],
            name=op.f("fk_blur_exports_file_id_drive_files"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"],
            name=op.f("fk_blur_exports_requested_by_users"), ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')",
            name=op.f("ck_blur_exports_status_valid"),
        ),
    )
    op.create_index(
        op.f("ix_blur_exports_org_id"), "blur_exports", ["org_id"],
    )
    op.create_index(
        op.f("ix_blur_exports_blur_job_id"), "blur_exports", ["blur_job_id"],
    )
    op.create_index(
        op.f("ix_blur_exports_requested_by"), "blur_exports", ["requested_by"],
    )
    op.create_index(
        "ix_blur_exports_org_requested", "blur_exports",
        ["org_id", "requested_at"],
    )
    op.create_index(
        "ix_blur_exports_active", "blur_exports",
        ["org_id", "status"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    # Dedupe: one export per (parent job, category set, format) within
    # the service layer's idempotency window. Query is keyed by this
    # composite so it hits a single btree lookup.
    op.create_index(
        "ix_blur_exports_dedupe", "blur_exports",
        ["blur_job_id", "categories_hash", "format", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_blur_exports_dedupe", table_name="blur_exports")
    op.drop_index("ix_blur_exports_active", table_name="blur_exports")
    op.drop_index("ix_blur_exports_org_requested", table_name="blur_exports")
    op.drop_index(op.f("ix_blur_exports_requested_by"), table_name="blur_exports")
    op.drop_index(op.f("ix_blur_exports_blur_job_id"), table_name="blur_exports")
    op.drop_index(op.f("ix_blur_exports_org_id"), table_name="blur_exports")
    op.drop_table("blur_exports")

    op.drop_column("blur_jobs", "phase")
    op.drop_column("blur_jobs", "progress_pct")
    op.drop_column("blur_jobs", "mask_s3_keys")
