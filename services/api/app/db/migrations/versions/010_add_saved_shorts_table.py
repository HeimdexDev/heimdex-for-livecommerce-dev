"""Add saved_shorts table for user-curated shorts

Revision ID: 010_add_saved_shorts_table
Revises: 009_set_devorg_auth0_org_id
Create Date: 2026-02-18

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010_add_saved_shorts_table"
down_revision: str | None = "009_set_devorg_auth0_org_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "saved_shorts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("video_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("scene_ids", sa.JSON(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_shorts")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_saved_shorts_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_saved_shorts_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_saved_shorts_org_id"), "saved_shorts", ["org_id"])
    op.create_index(op.f("ix_saved_shorts_user_id"), "saved_shorts", ["user_id"])
    op.create_index(op.f("ix_saved_shorts_video_id"), "saved_shorts", ["video_id"])
    op.create_index(
        "ix_saved_shorts_org_id_user_id",
        "saved_shorts",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_shorts_org_id_user_id", table_name="saved_shorts")
    op.drop_index(op.f("ix_saved_shorts_video_id"), table_name="saved_shorts")
    op.drop_index(op.f("ix_saved_shorts_user_id"), table_name="saved_shorts")
    op.drop_index(op.f("ix_saved_shorts_org_id"), table_name="saved_shorts")
    op.drop_table("saved_shorts")
