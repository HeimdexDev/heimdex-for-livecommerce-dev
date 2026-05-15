"""Add image caption metadata columns to drive_files.

Revision ID: 046_add_image_caption_metadata
Revises: 045_shorts_render_composition_hash

Tracks which engine + prompt version produced the caption on each row so
we can target re-backfill at a specific generation if the prompt drifts,
and when the caption was generated (for freshness reporting).

Why these live on ``drive_files`` rather than a ``scenes`` table:
- Scenes live in OpenSearch, not Postgres. One drive_file == one scene
  row in OpenSearch (for images) or multiple scene rows (for videos).
- The existing ``caption_status`` column is already on drive_files
  (migration 014). These new columns sit next to it for consistency.
- Images are uniquely identified by drive_files row → we can filter
  the backfill query by ``mime_type LIKE 'image/%'``.

Columns:
- caption_engine        VARCHAR(32)   which backend produced the caption
                                       ("openai", "qwen2vl", "internvl2", ...)
- caption_prompt_version VARCHAR(64)  prompt asset version for drift
                                       detection and targeted re-backfill
- caption_generated_at  TIMESTAMPTZ   when the caption was last written

Composite index on (mime_type, caption_status, caption_prompt_version)
supports the backfill query:

    SELECT id FROM drive_files
    WHERE mime_type LIKE 'image/%'
      AND (caption_status IS NULL
           OR caption_status != 'done'
           OR caption_prompt_version != :current_version)
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "046_add_image_caption_metadata"
down_revision: str | None = "045_shorts_render_composition_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drive_files",
        sa.Column("caption_engine", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "drive_files",
        sa.Column("caption_prompt_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "drive_files",
        sa.Column(
            "caption_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_drive_files_caption_backfill",
        "drive_files",
        ["mime_type", "caption_status", "caption_prompt_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_drive_files_caption_backfill", table_name="drive_files")
    op.drop_column("drive_files", "caption_generated_at")
    op.drop_column("drive_files", "caption_prompt_version")
    op.drop_column("drive_files", "caption_engine")
