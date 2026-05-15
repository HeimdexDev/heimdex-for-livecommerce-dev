"""Add Drive OAuth and folder-scoped connection support

Revision ID: 018_add_drive_oauth_support
Revises: 017_add_sync_requested_at
Create Date: 2026-02-23

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018_add_drive_oauth_support"
down_revision: str | None = "017_add_sync_requested_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drive_connections",
        sa.Column("scope_type", sa.String(length=32), server_default="drive", nullable=False),
    )
    op.add_column("drive_connections", sa.Column("folder_id", sa.String(length=256), nullable=True))
    op.add_column("drive_connections", sa.Column("folder_name", sa.String(length=500), nullable=True))
    op.add_column("drive_connections", sa.Column("folder_path", sa.Text(), nullable=True))

    op.alter_column("drive_connections", "drive_id", existing_type=sa.String(length=128), nullable=True)

    op.drop_constraint("uq_drive_connections_org_drive", "drive_connections", type_="unique")

    op.create_index(
        "uq_drive_connections_org_drive_not_null",
        "drive_connections",
        ["org_id", "drive_id"],
        unique=True,
        postgresql_where=sa.text("drive_id IS NOT NULL"),
    )
    op.create_index(
        "uq_drive_connections_org_folder_not_null",
        "drive_connections",
        ["org_id", "folder_id"],
        unique=True,
        postgresql_where=sa.text("folder_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_drive_connections_org_folder_not_null", table_name="drive_connections")
    op.drop_index("uq_drive_connections_org_drive_not_null", table_name="drive_connections")

    op.create_unique_constraint(
        "uq_drive_connections_org_drive",
        "drive_connections",
        ["org_id", "drive_id"],
    )

    op.execute(sa.text("DELETE FROM drive_connections WHERE drive_id IS NULL"))
    op.alter_column("drive_connections", "drive_id", existing_type=sa.String(length=128), nullable=False)

    op.drop_column("drive_connections", "folder_path")
    op.drop_column("drive_connections", "folder_name")
    op.drop_column("drive_connections", "folder_id")
    op.drop_column("drive_connections", "scope_type")
