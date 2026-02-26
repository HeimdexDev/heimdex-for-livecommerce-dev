"""Add original_s3_key and original_size_bytes columns to drive_files

Supports GPU transcode migration: drive-worker uploads originals to S3,
transcode-worker downloads from S3 for GPU-accelerated transcoding.

Revision ID: 022_add_original_s3_columns
Revises: 021_add_connection_lease_columns
Create Date: 2026-02-26

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "022_add_original_s3_columns"
down_revision: str | None = "021_add_connection_lease_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drive_files",
        sa.Column("original_s3_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "drive_files",
        sa.Column("original_size_bytes", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("drive_files", "original_size_bytes")
    op.drop_column("drive_files", "original_s3_key")
