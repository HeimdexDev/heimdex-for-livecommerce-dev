"""Add video_summaries table for AI-generated video summaries.

Revision ID: 042_add_video_summaries
Revises: 041_add_scene_overrides
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "042_add_video_summaries"
down_revision = "041_add_scene_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "video_summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("video_id", sa.String(255), nullable=False),
        # AI-generated summary
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
        sa.Column("model", sa.String(100), nullable=False, server_default=""),
        sa.Column("prompt_version", sa.String(50), nullable=False, server_default="v1"),
        # User override
        sa.Column("summary_override", sa.Text, nullable=True),
        sa.Column("edited_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        # Metadata
        sa.Column("scene_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("input_hash", sa.String(64), nullable=False, server_default=""),
        sa.UniqueConstraint("org_id", "video_id", name="uq_video_summaries_org_video"),
    )
    op.create_index("ix_video_summaries_org_id", "video_summaries", ["org_id"])


def downgrade() -> None:
    op.drop_index("ix_video_summaries_org_id", table_name="video_summaries")
    op.drop_table("video_summaries")
