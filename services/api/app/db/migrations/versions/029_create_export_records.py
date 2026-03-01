"""Create export_records table for async proxy-pack exports.

Revision ID: 029_create_export_records
Revises: 028_create_scene_basket_tables
Create Date: 2026-03-02

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "029_create_export_records"
down_revision: str | None = "028_create_scene_basket_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "export_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("export_hash", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("s3_key", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("clip_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("proxy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sequence_name", sa.String(length=200), nullable=False, server_default="Heimdex Export"),
        sa.Column("request_body", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_export_records_org_hash",
        "export_records",
        ["org_id", "export_hash"],
        unique=False,
    )
    op.create_index(
        "ix_export_records_status",
        "export_records",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status = 'ready'"),
    )
    op.create_index(
        "ix_export_records_expires",
        "export_records",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'ready'"),
    )


def downgrade() -> None:
    op.drop_index("ix_export_records_expires", table_name="export_records")
    op.drop_index("ix_export_records_status", table_name="export_records")
    op.drop_index("ix_export_records_org_hash", table_name="export_records")
    op.drop_table("export_records")
