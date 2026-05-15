"""Add missing updated_at column to face_exemplars

Migration 023 created face_exemplars with only created_at, but the
FaceExemplar model inherits TimestampMixin which also provides updated_at.

Revision ID: 025_add_updated_at_to_face_exemplars
Revises: 024_add_face_status_columns
Create Date: 2026-02-27

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "025_add_updated_at_to_face_exemplars"
down_revision: str | None = "024_add_face_status_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "face_exemplars",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("face_exemplars", "updated_at")
