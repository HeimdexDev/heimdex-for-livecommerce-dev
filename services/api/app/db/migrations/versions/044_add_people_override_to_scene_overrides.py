"""Add people_cluster_ids override columns to scene_overrides table.

Revision ID: 044_add_people_override
Revises: 043_replace_ivfflat_with_hnsw_index
"""
from alembic import op
import sqlalchemy as sa

revision = "044_add_people_override"
down_revision = "043_replace_ivfflat_with_hnsw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scene_overrides",
        sa.Column("people_cluster_ids_json", sa.Text, nullable=True),
    )
    op.add_column(
        "scene_overrides",
        sa.Column("original_people_cluster_ids_json", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scene_overrides", "original_people_cluster_ids_json")
    op.drop_column("scene_overrides", "people_cluster_ids_json")
