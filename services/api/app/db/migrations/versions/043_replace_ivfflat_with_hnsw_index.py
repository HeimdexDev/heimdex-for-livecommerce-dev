"""Replace IVFFlat with HNSW index on face_identities centroid_embedding.

HNSW indexes new rows immediately (no recall degradation on insert),
gives >99% recall at <100k vectors, and has sub-ms query time.
IVFFlat with lists=100 falls back to sequential scan for small datasets
and silently degrades recall as new rows are inserted without reindexing.

Revision ID: 043_replace_ivfflat_with_hnsw
Revises: 042_add_video_summaries
Create Date: 2026-04-10
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "043_replace_ivfflat_with_hnsw"
down_revision: str | None = "042_add_video_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_face_identities_embedding")
    op.execute("""
        CREATE INDEX ix_face_identities_embedding
        ON face_identities USING hnsw (centroid_embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_face_identities_embedding")
    op.execute("""
        CREATE INDEX ix_face_identities_embedding
        ON face_identities USING ivfflat (centroid_embedding vector_cosine_ops)
        WITH (lists = 100)
    """)
