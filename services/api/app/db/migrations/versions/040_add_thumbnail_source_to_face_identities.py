"""Add thumbnail_source and selected_exemplar_id to face_identities.

Revision ID: 040_add_thumbnail_source
Revises: 039_add_stt_split_columns
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "040_add_thumbnail_source"
down_revision = "039_add_stt_split_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "face_identities",
        sa.Column("thumbnail_source", sa.String(16), nullable=False, server_default="auto"),
    )
    op.add_column(
        "face_identities",
        sa.Column(
            "selected_exemplar_id",
            UUID(as_uuid=True),
            sa.ForeignKey("face_exemplars.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("face_identities", "selected_exemplar_id")
    op.drop_column("face_identities", "thumbnail_source")
