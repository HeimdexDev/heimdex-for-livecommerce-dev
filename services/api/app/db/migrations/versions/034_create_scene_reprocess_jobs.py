from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "034_create_scene_reprocess_jobs"
down_revision: str | None = "033_create_youtube_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "scene_reprocess_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("video_id", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("scene_params", postgresql.JSONB(), nullable=False),
        sa.Column("proxy_s3_key", sa.Text(), nullable=False),
        sa.Column("scene_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scene_reprocess_jobs_org_video",
        "scene_reprocess_jobs",
        ["org_id", "video_id"],
        unique=False,
    )
    op.create_index(
        "ix_scene_reprocess_jobs_status",
        "scene_reprocess_jobs",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_scene_reprocess_jobs_status", table_name="scene_reprocess_jobs")
    op.drop_index("ix_scene_reprocess_jobs_org_video", table_name="scene_reprocess_jobs")
    op.drop_table("scene_reprocess_jobs")
