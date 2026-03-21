"""Add text_templates table for reusable text styling presets

Revision ID: 038_add_text_templates_table
Revises: 037_add_updated_at_to_shorts_render_jobs
Create Date: 2026-03-19

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "038_add_text_templates_table"
down_revision: str | None = "037_add_updated_at_to_shorts_render_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "text_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "font_family",
            sa.String(100),
            nullable=False,
            server_default=sa.text("'Noto Sans KR'"),
        ),
        sa.Column(
            "font_size_px",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("48"),
        ),
        sa.Column(
            "font_color",
            sa.String(9),
            nullable=False,
            server_default=sa.text("'#FFFFFF'"),
        ),
        sa.Column(
            "font_weight",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("700"),
        ),
        sa.Column(
            "line_height",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.4"),
        ),
        sa.Column(
            "letter_spacing",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "position_x",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column(
            "position_y",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.85"),
        ),
        sa.Column(
            "text_align",
            sa.String(10),
            nullable=False,
            server_default=sa.text("'center'"),
        ),
        sa.Column(
            "shadow_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "shadow_color",
            sa.String(9),
            nullable=False,
            server_default=sa.text("'#000000'"),
        ),
        sa.Column(
            "shadow_offset_x",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
        sa.Column(
            "shadow_offset_y",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
        sa.Column(
            "shadow_blur",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("4"),
        ),
        sa.Column(
            "background_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("background_color", sa.String(9), nullable=True),
        sa.Column(
            "background_padding",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("8"),
        ),
        sa.Column(
            "is_system_preset",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_text_templates")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_text_templates_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_text_templates_user_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_text_templates_org_id"),
        "text_templates",
        ["org_id"],
    )
    op.create_index(
        "ix_text_templates_org_user",
        "text_templates",
        ["org_id", "user_id"],
    )
    op.create_index(
        op.f("ix_text_templates_is_system_preset"),
        "text_templates",
        ["is_system_preset"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_text_templates_is_system_preset"),
        table_name="text_templates",
    )
    op.drop_index(
        "ix_text_templates_org_user",
        table_name="text_templates",
    )
    op.drop_index(
        op.f("ix_text_templates_org_id"),
        table_name="text_templates",
    )
    op.drop_table("text_templates")
