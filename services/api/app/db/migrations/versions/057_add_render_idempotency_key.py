"""Add ``idempotency_key`` to shorts_render_jobs for scoped dedupe.

Found on staging 2026-05-06: the auto-shorts wizard runner widens
the composition-hash dedupe window to ``lease_seconds + 60`` (~360s)
so a crash-retry of the SAME scan_job doesn't leak an orphan render.
But the dedupe is scoped only by ``(org_id, user_id, composition_hash)``,
so two DIFFERENT scan_jobs that happen to produce the same composition
ALSO collapse — and the user sees one wizard card pointing at the
same render as another.

Concrete failure: scan_order ``04413e8a`` produced 5 wizard children;
the LLM enumerator assigned the same product (``단백질 바``) to scan
jobs 1 and 5; their compositions matched bit-for-bit; the dedupe
returned the same render row for both.

Fix: add a nullable ``idempotency_key`` column + extend the dedupe
index. Callers that need crash-retry safety on a specific upstream
key (the wizard runner: ``scan_job_id``) pass it; callers that don't
(direct user click on POST /api/shorts/render) leave it NULL and
keep legacy semantics (NULL-vs-NULL match).

This migration is strictly additive:
  - column is nullable; existing rows stay NULL
  - dedupe index DROPped + RECREATEd with the new column appended
    (order matters for B-tree usage: org_id, user_id, hash, key,
    created_at).

No backfill needed. Existing rows participate in NULL-keyed dedupe
identical to pre-migration behaviour.

Plan: ``.claude/plans/auto-shorts-subtitle-editor-2026-05-06.md``
follow-up section "dedupe fix" (added 2026-05-06 after the staging
investigation).

Revision ID: 057_add_render_idempotency_key
Revises: 056_add_render_refinement_chain
Create Date: 2026-05-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "057_add_render_idempotency_key"
down_revision: str | None = "056_add_render_refinement_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEDUPE_INDEX_NAME = "ix_shorts_render_jobs_dedupe"


def upgrade() -> None:
    op.add_column(
        "shorts_render_jobs",
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
    )

    # Drop and recreate the dedupe index with the new key column.
    # B-tree column order: most-selective filters first (org+user),
    # then composition_hash, then idempotency_key (NULL or matched
    # scan_job_id), then created_at for the time-window range scan.
    op.drop_index(_DEDUPE_INDEX_NAME, table_name="shorts_render_jobs")
    op.create_index(
        _DEDUPE_INDEX_NAME,
        "shorts_render_jobs",
        ["org_id", "user_id", "composition_hash", "idempotency_key", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # Reverse: restore the original dedupe index shape, then drop
    # the column.
    op.drop_index(_DEDUPE_INDEX_NAME, table_name="shorts_render_jobs")
    op.create_index(
        _DEDUPE_INDEX_NAME,
        "shorts_render_jobs",
        ["org_id", "user_id", "composition_hash", "created_at"],
        unique=False,
    )
    op.drop_column("shorts_render_jobs", "idempotency_key")
