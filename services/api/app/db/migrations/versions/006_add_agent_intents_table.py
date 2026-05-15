"""Add agent_intents table for deep link intent exchange

Revision ID: 006_add_agent_intents_table
Revises: 005_add_pairing_codes_table
Create Date: 2026-02-16

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006_add_agent_intents_table"
down_revision: str | None = "005_add_pairing_codes_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_intents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("intent_code", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("used_by_device_id", sa.UUID(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_intents")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_agent_intents_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["used_by_device_id"],
            ["devices.id"],
            name=op.f("fk_agent_intents_used_by_device_id_devices"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_agent_intents_created_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_agent_intents_device_id_devices"),
        ),
    )
    op.create_index(op.f("ix_agent_intents_org_id"), "agent_intents", ["org_id"])
    op.create_index(
        "uq_agent_intents_intent_code",
        "agent_intents",
        ["intent_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_agent_intents_intent_code", table_name="agent_intents")
    op.drop_index(op.f("ix_agent_intents_org_id"), table_name="agent_intents")
    op.drop_table("agent_intents")
