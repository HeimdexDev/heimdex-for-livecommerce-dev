"""Create scene basket tables.

Revision ID: 028_create_scene_basket_tables
Revises: 027_add_video_metadata_columns
Create Date: 2026-03-01

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "028_create_scene_basket_tables"
down_revision: str | None = "027_add_video_metadata_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "scene_baskets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default="Untitled"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scene_baskets_org_user", "scene_baskets", ["org_id", "user_id"], unique=False)

    _ = op.create_table(
        "scene_basket_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("basket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_id", sa.String(length=255), nullable=False),
        sa.Column("video_id", sa.String(length=64), nullable=False),
        sa.Column("video_title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["basket_id"], ["scene_baskets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("basket_id", "scene_id", name="uq_basket_items_basket_scene"),
    )
    op.create_index("ix_scene_basket_items_basket_id", "scene_basket_items", ["basket_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scene_basket_items_basket_id", table_name="scene_basket_items")
    op.drop_table("scene_basket_items")
    op.drop_index("ix_scene_baskets_org_user", table_name="scene_baskets")
    op.drop_table("scene_baskets")
