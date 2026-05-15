"""Add web_view_link column to drive_files

Stores Google Drive webViewLink for deep-linking to the source file.

Revision ID: 026_add_web_view_link
Revises: 025_add_updated_at_to_face_exemplars
Create Date: 2026-02-28

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "026_add_web_view_link"
down_revision: str | None = "025_add_updated_at_to_face_exemplars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drive_files", sa.Column("web_view_link", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("drive_files", "web_view_link")
