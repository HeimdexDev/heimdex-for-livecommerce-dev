"""Add missing indexes on frequently-queried columns

drive_files.is_deleted — filtered in 10+ repository methods
drive_files.google_file_id — looked up in get_by_google_file_id()
export_records.status — filtered in expire_stale()

Revision ID: 032_add_missing_indexes
Revises: 031_create_search_events
Create Date: 2026-03-07

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "032_add_missing_indexes"
down_revision: str | None = "031_create_search_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_drive_files_is_deleted",
        "drive_files",
        ["is_deleted"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_drive_files_org_google_file",
        "drive_files",
        ["org_id", "google_file_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_export_records_status",
        "export_records",
        ["status"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_export_records_status", table_name="export_records", if_exists=True)
    op.drop_index("ix_drive_files_org_google_file", table_name="drive_files", if_exists=True)
    op.drop_index("ix_drive_files_is_deleted", table_name="drive_files", if_exists=True)
