"""Add scene_overrides table for user-editable captions/transcripts/tags.

Revision ID: 041_add_scene_overrides
Revises: 040_add_thumbnail_source
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "041_add_scene_overrides"
down_revision = "040_add_thumbnail_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scene_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_id", sa.String(128), nullable=False),
        sa.Column("video_id", sa.String(128), nullable=False),
        sa.Column("edited_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        # Override values
        sa.Column("scene_caption", sa.Text, nullable=True),
        sa.Column("transcript_raw", sa.Text, nullable=True),
        sa.Column("speaker_transcript", sa.Text, nullable=True),
        sa.Column("ai_tags_json", sa.Text, nullable=True),
        # Original worker values for reset
        sa.Column("original_scene_caption", sa.Text, nullable=True),
        sa.Column("original_transcript_raw", sa.Text, nullable=True),
        sa.Column("original_speaker_transcript", sa.Text, nullable=True),
        sa.Column("original_ai_tags_json", sa.Text, nullable=True),
        # Tracks which fields are overridden
        sa.Column("overridden_fields", sa.String(256), nullable=False, server_default=""),
        sa.UniqueConstraint("org_id", "scene_id", name="uq_scene_overrides_org_scene"),
    )
    op.create_index("ix_scene_overrides_org_video", "scene_overrides", ["org_id", "video_id"])


def downgrade() -> None:
    op.drop_index("ix_scene_overrides_org_video", table_name="scene_overrides")
    op.drop_table("scene_overrides")
