"""Create drive_secrets, drive_connections, drive_files tables

Revision ID: 012_create_drive_tables
Revises: 011_add_people_exclude_preferences_table
Create Date: 2026-02-19

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012_create_drive_tables"
down_revision: str | None = "011_add_people_exclude_preferences_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # drive_secrets first (no FK deps except orgs)
    _ = op.create_table(
        "drive_secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("secret_type", sa.String(64), server_default="service_account_key", nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("impersonate_email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_secrets")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"],
            name=op.f("fk_drive_secrets_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "secret_type", name="uq_drive_secrets_org_type"),
    )
    op.create_index(op.f("ix_drive_secrets_org_id"), "drive_secrets", ["org_id"])

    # drive_connections (FK to orgs, libraries)
    _ = op.create_table(
        "drive_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("library_id", sa.UUID(), nullable=False),
        sa.Column("drive_id", sa.String(128), nullable=False),
        sa.Column("drive_name", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        sa.Column("change_token", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_connections")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"],
            name=op.f("fk_drive_connections_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["library_id"], ["libraries.id"],
            name=op.f("fk_drive_connections_library_id_libraries"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "drive_id", name="uq_drive_connections_org_drive"),
    )
    op.create_index(op.f("ix_drive_connections_org_id"), "drive_connections", ["org_id"])
    op.create_index(op.f("ix_drive_connections_library_id"), "drive_connections", ["library_id"])
    op.create_index("ix_drive_connections_status", "drive_connections", ["status"])

    # drive_files (FK to orgs, drive_connections)
    _ = op.create_table(
        "drive_files",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("google_file_id", sa.String(256), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("md5_checksum", sa.String(64), nullable=True),
        sa.Column("google_modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("google_created_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drive_path", sa.Text(), nullable=True),
        sa.Column("video_id", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("proxy_s3_key", sa.Text(), nullable=True),
        sa.Column("proxy_duration_ms", sa.Integer(), nullable=True),
        sa.Column("proxy_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("thumbnail_s3_prefix", sa.Text(), nullable=True),
        sa.Column("scene_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="3", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_drive_files")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"],
            name=op.f("fk_drive_files_org_id_orgs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"], ["drive_connections.id"],
            name=op.f("fk_drive_files_connection_id_drive_connections"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "google_file_id", name="uq_drive_files_org_file"),
    )
    op.create_index(op.f("ix_drive_files_org_id"), "drive_files", ["org_id"])
    op.create_index(op.f("ix_drive_files_connection_id"), "drive_files", ["connection_id"])
    op.create_index("ix_drive_files_processing_status", "drive_files", ["processing_status"])
    op.create_index("ix_drive_files_video_id", "drive_files", ["video_id"])


def downgrade() -> None:
    op.drop_index("ix_drive_files_video_id", table_name="drive_files")
    op.drop_index("ix_drive_files_processing_status", table_name="drive_files")
    op.drop_index(op.f("ix_drive_files_connection_id"), table_name="drive_files")
    op.drop_index(op.f("ix_drive_files_org_id"), table_name="drive_files")
    op.drop_table("drive_files")

    op.drop_index("ix_drive_connections_status", table_name="drive_connections")
    op.drop_index(op.f("ix_drive_connections_library_id"), table_name="drive_connections")
    op.drop_index(op.f("ix_drive_connections_org_id"), table_name="drive_connections")
    op.drop_table("drive_connections")

    op.drop_index(op.f("ix_drive_secrets_org_id"), table_name="drive_secrets")
    op.drop_table("drive_secrets")
