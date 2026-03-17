"""Add shorts_render_jobs table for render job metadata

Revision ID: 036_add_shorts_render_jobs_table
Revises: 035_add_org_settings
Create Date: 2026-03-17

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "036_add_shorts_render_jobs_table"
down_revision: str | None = "035_add_org_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "shorts_render_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("video_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("input_spec", JSONB, nullable=False),
        sa.Column("output_s3_key", sa.String(512), nullable=True),
        sa.Column("output_duration_ms", sa.Integer(), nullable=True),
        sa.Column("output_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("render_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shorts_render_jobs")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_shorts_render_jobs_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_shorts_render_jobs_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_shorts_render_jobs_org_id"),
        "shorts_render_jobs",
        ["org_id"],
    )
    op.create_index(
        op.f("ix_shorts_render_jobs_user_id"),
        "shorts_render_jobs",
        ["user_id"],
    )
    op.create_index(
        "ix_shorts_render_jobs_org_id_user_id",
        "shorts_render_jobs",
        ["org_id", "user_id"],
    )
    op.create_index(
        op.f("ix_shorts_render_jobs_status"),
        "shorts_render_jobs",
        ["status"],
    )
    op.create_index(
        op.f("ix_shorts_render_jobs_expires_at"),
        "shorts_render_jobs",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_shorts_render_jobs_expires_at"),
        table_name="shorts_render_jobs",
    )
    op.drop_index(
        op.f("ix_shorts_render_jobs_status"),
        table_name="shorts_render_jobs",
    )
    op.drop_index(
        "ix_shorts_render_jobs_org_id_user_id",
        table_name="shorts_render_jobs",
    )
    op.drop_index(
        op.f("ix_shorts_render_jobs_user_id"),
        table_name="shorts_render_jobs",
    )
    op.drop_index(
        op.f("ix_shorts_render_jobs_org_id"),
        table_name="shorts_render_jobs",
    )
    op.drop_table("shorts_render_jobs")
