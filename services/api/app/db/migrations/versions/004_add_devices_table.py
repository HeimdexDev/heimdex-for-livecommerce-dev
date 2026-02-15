"""Add devices table for per-device authentication

Revision ID: 004_add_devices_table
Revises: 003_add_org_agent_api_key
Create Date: 2026-02-15

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_add_devices_table"
down_revision: str | None = "003_add_org_agent_api_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("device_public_id", sa.String(64), nullable=False),
        sa.Column("device_secret_hash", sa.String(128), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devices")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_devices_org_id_orgs"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_devices_org_id"), "devices", ["org_id"])
    op.create_index(
        "uq_devices_org_id_device_public_id",
        "devices",
        ["org_id", "device_public_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_devices_org_id_device_public_id", table_name="devices")
    op.drop_index(op.f("ix_devices_org_id"), table_name="devices")
    op.drop_table("devices")
