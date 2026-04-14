"""Add blur_jobs table for user-triggered PII blur runs

Revision ID: 047_add_blur_jobs_table
Revises: 046_add_image_caption_metadata
Create Date: 2026-04-14

Creates a single new table. No existing tables are touched. Safe to
roll back — ``blur_enabled=false`` until explicitly turned on per
environment, so nothing writes to this table until someone opts in.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "047_add_blur_jobs_table"
down_revision: str | None = "046_add_image_caption_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "blur_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("video_id", sa.String(255), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("options", JSONB, nullable=False),
        sa.Column("options_hash", sa.String(64), nullable=False),
        sa.Column("source_s3_key", sa.String(512), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("blurred_s3_key", sa.String(512), nullable=True),
        sa.Column("manifest_s3_key", sa.String(512), nullable=True),
        sa.Column("detections_summary", JSONB, nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blur_jobs")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"],
            name=op.f("fk_blur_jobs_org_id_orgs"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["drive_files.id"],
            name=op.f("fk_blur_jobs_file_id_drive_files"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"],
            name=op.f("fk_blur_jobs_requested_by_users"), ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed','cancelled')",
            name=op.f("ck_blur_jobs_status_valid"),
        ),
    )
    op.create_index(
        op.f("ix_blur_jobs_org_id"), "blur_jobs", ["org_id"],
    )
    op.create_index(
        op.f("ix_blur_jobs_file_id"), "blur_jobs", ["file_id"],
    )
    op.create_index(
        op.f("ix_blur_jobs_requested_by"), "blur_jobs", ["requested_by"],
    )
    op.create_index(
        "ix_blur_jobs_org_requested", "blur_jobs",
        ["org_id", "requested_at"],
    )
    op.create_index(
        "ix_blur_jobs_file_status", "blur_jobs",
        ["file_id", "status"],
    )
    # Partial index — only rows still in flight. Keeps the concurrency
    # cap query cheap even after millions of terminal rows accumulate.
    op.create_index(
        "ix_blur_jobs_active", "blur_jobs",
        ["org_id", "status"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    # Dedupe lookup: (org, file, options_hash) within a time window.
    op.create_index(
        "ix_blur_jobs_dedupe", "blur_jobs",
        ["org_id", "file_id", "options_hash", "requested_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_blur_jobs_dedupe", table_name="blur_jobs")
    op.drop_index("ix_blur_jobs_active", table_name="blur_jobs")
    op.drop_index("ix_blur_jobs_file_status", table_name="blur_jobs")
    op.drop_index("ix_blur_jobs_org_requested", table_name="blur_jobs")
    op.drop_index(op.f("ix_blur_jobs_requested_by"), table_name="blur_jobs")
    op.drop_index(op.f("ix_blur_jobs_file_id"), table_name="blur_jobs")
    op.drop_index(op.f("ix_blur_jobs_org_id"), table_name="blur_jobs")
    op.drop_table("blur_jobs")
