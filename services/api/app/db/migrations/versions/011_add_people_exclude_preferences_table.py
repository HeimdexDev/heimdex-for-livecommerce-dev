"""Add people_exclude_preferences table for user-specific face exclusion

Revision ID: 011_add_people_exclude_preferences_table
Revises: 010_add_saved_shorts_table
Create Date: 2026-02-18

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_add_people_exclude_preferences_table"
down_revision: str | None = "010_add_saved_shorts_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "people_exclude_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("person_cluster_id", sa.String(64), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_people_exclude_preferences")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_people_exclude_preferences_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_people_exclude_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "org_id", "user_id", "person_cluster_id",
            name="uq_people_exclude_prefs_org_user_person",
        ),
    )
    op.create_index(
        op.f("ix_people_exclude_preferences_org_id"),
        "people_exclude_preferences",
        ["org_id"],
    )
    op.create_index(
        op.f("ix_people_exclude_preferences_user_id"),
        "people_exclude_preferences",
        ["user_id"],
    )
    op.create_index(
        "ix_people_exclude_prefs_org_user",
        "people_exclude_preferences",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_people_exclude_prefs_org_user",
        table_name="people_exclude_preferences",
    )
    op.drop_index(
        op.f("ix_people_exclude_preferences_user_id"),
        table_name="people_exclude_preferences",
    )
    op.drop_index(
        op.f("ix_people_exclude_preferences_org_id"),
        table_name="people_exclude_preferences",
    )
    op.drop_table("people_exclude_preferences")
