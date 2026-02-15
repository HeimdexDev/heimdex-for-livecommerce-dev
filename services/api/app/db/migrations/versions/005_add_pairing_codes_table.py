"""Add pairing_codes table for device pairing flow

Revision ID: 005_add_pairing_codes_table
Revises: 004_add_devices_table
Create Date: 2026-02-15

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_add_pairing_codes_table"
down_revision: str | None = "004_add_devices_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("used_by_device_id", sa.UUID(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pairing_codes")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
            name=op.f("fk_pairing_codes_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["used_by_device_id"],
            ["devices.id"],
            name=op.f("fk_pairing_codes_used_by_device_id_devices"),
        ),
    )
    op.create_index(op.f("ix_pairing_codes_org_id"), "pairing_codes", ["org_id"])
    op.create_index(
        "uq_pairing_codes_org_id_code",
        "pairing_codes",
        ["org_id", "code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_pairing_codes_org_id_code", table_name="pairing_codes")
    op.drop_index(op.f("ix_pairing_codes_org_id"), table_name="pairing_codes")
    op.drop_table("pairing_codes")
