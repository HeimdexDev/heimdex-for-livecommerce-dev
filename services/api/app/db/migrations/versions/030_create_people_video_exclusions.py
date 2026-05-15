"""Create people_video_exclusions table for per-video person exclusion

Revision ID: 030_create_people_video_exclusions
Revises: 029_create_export_records
Create Date: 2026-03-06

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "030_create_people_video_exclusions"
down_revision: str | None = "029_create_export_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "people_video_exclusions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("person_cluster_id", sa.String(64), nullable=False),
        sa.Column("video_id", sa.String(128), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people_video_exclusions")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_people_video_exclusions_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_people_video_exclusions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "org_id", "user_id", "person_cluster_id", "video_id",
            name="uq_video_exclusion",
        ),
    )
    op.create_index(
        "ix_video_excl_org_user",
        "people_video_exclusions",
        ["org_id", "user_id"],
    )
    op.create_index(
        "ix_video_excl_org_cluster",
        "people_video_exclusions",
        ["org_id", "person_cluster_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_video_excl_org_cluster",
        table_name="people_video_exclusions",
    )
    op.drop_index(
        "ix_video_excl_org_user",
        table_name="people_video_exclusions",
    )
    op.drop_table("people_video_exclusions")
