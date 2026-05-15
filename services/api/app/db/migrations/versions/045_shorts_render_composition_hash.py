"""Add composition_hash to shorts_render_jobs for idempotent POST dedupe.

Revision ID: 045_shorts_render_composition_hash
Revises: 044_add_people_override

The column is deterministic over the normalized composition spec + user
scope. A composite index supports the `find_recent_duplicate` query:
given (org_id, user_id, composition_hash, created_at > cutoff), return
the most recent match. Existing rows stay NULL and are invisible to the
dedupe query by design — we only prevent NEW duplicates going forward.
"""
from alembic import op
import sqlalchemy as sa

revision = "045_shorts_render_composition_hash"
down_revision = "044_add_people_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shorts_render_jobs",
        sa.Column("composition_hash", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_shorts_render_jobs_dedupe",
        "shorts_render_jobs",
        ["org_id", "user_id", "composition_hash", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_shorts_render_jobs_dedupe", table_name="shorts_render_jobs")
    op.drop_column("shorts_render_jobs", "composition_hash")
