"""Create subtitle_presets table for shorts editor V2

Backs the named-preset save/apply UI in the shorts editor's left panel.
Replaces browser localStorage so presets follow the user across devices.

Org-shared via ``is_shared`` — anyone in the same org can READ a shared
preset, but only the creator (``user_id``) can mutate or delete it. The
partial index on ``(org_id, is_shared) WHERE is_shared = true`` keeps the
shared-listing query cheap as the table grows.

Revision ID: 050_create_subtitle_presets
Revises: 049_create_worker_events
Create Date: 2026-04-28

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "050_create_subtitle_presets"
down_revision: str | None = "049_create_worker_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subtitle_presets",
        sa.Column("id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("style_json", JSONB, nullable=False),
        sa.Column(
            "is_shared",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('text', 'background')",
            name="ck_subtitle_presets_kind",
        ),
    )
    op.create_index(
        "ix_subtitle_presets_org_user",
        "subtitle_presets",
        ["org_id", "user_id"],
    )
    # Partial index for the "presets shared in my org" lookup. Most rows are
    # private; keeping the shared-only slice small makes the org-shared query
    # cheap as the table grows.
    op.create_index(
        "ix_subtitle_presets_org_shared",
        "subtitle_presets",
        ["org_id"],
        postgresql_where=sa.text("is_shared = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_subtitle_presets_org_shared", table_name="subtitle_presets")
    op.drop_index("ix_subtitle_presets_org_user", table_name="subtitle_presets")
    op.drop_table("subtitle_presets")
