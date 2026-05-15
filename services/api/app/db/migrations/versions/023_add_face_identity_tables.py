"""Add pgvector extension and face identity tables

Supports GPU face detection worker: org-wide face identity matching
using pgvector for nearest-neighbor cosine similarity search.

Revision ID: 023_add_face_identity_tables
Revises: 022_add_original_s3_columns
Create Date: 2026-02-27

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "023_add_face_identity_tables"
down_revision: str | None = "022_add_original_s3_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension (requires pgvector/pgvector Docker image)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # face_identities -- org-scoped face centroids with 512-dim ArcFace embeddings
    op.execute("""
        CREATE TABLE face_identities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            cluster_id VARCHAR(64) NOT NULL,
            centroid_embedding vector(512) NOT NULL,
            exemplar_count INTEGER NOT NULL DEFAULT 1,
            best_quality FLOAT NOT NULL DEFAULT 0.0,
            best_thumbnail_video_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_face_identities_org_cluster UNIQUE (org_id, cluster_id)
        )
    """)
    op.execute("CREATE INDEX ix_face_identities_org_id ON face_identities (org_id)")
    op.execute(
        "COMMENT ON TABLE face_identities IS "
        "'Face identity centroids for cross-video person matching (pgvector)'"
    )

    # IVFFlat index for cosine similarity search on centroids.
    # lists=100 is appropriate for up to ~25K identities per org.
    # For small datasets (<1000), the planner falls back to sequential scan.
    op.execute("""
        CREATE INDEX ix_face_identities_embedding
        ON face_identities USING ivfflat (centroid_embedding vector_cosine_ops)
        WITH (lists = 100)
    """)

    # face_exemplars -- individual face detections linked to identities
    op.execute("""
        CREATE TABLE face_exemplars (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            identity_id UUID NOT NULL REFERENCES face_identities(id) ON DELETE CASCADE,
            org_id UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            video_id VARCHAR(255) NOT NULL,
            scene_id VARCHAR(255) NOT NULL,
            embedding vector(512) NOT NULL,
            quality FLOAT NOT NULL DEFAULT 0.0,
            bbox_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_face_exemplars_identity ON face_exemplars (identity_id)")
    op.execute("CREATE INDEX ix_face_exemplars_org_video ON face_exemplars (org_id, video_id)")
    op.execute(
        "COMMENT ON TABLE face_exemplars IS "
        "'Individual face exemplars linked to identities'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS face_exemplars")
    op.execute("DROP TABLE IF EXISTS face_identities")
    op.execute("DROP EXTENSION IF EXISTS vector")