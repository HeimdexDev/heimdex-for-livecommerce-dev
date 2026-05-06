"""Add refinement chain to shorts_render_jobs.

Powers the post-render Whisper subtitle refinement flow described in
``.claude/plans/auto-shorts-whisper-subtitles-2026-05-06.md``. PR 2 of 7.

Three additive columns on ``shorts_render_jobs``:

* ``replaced_by_render_job_id UUID NULL`` — forward pointer set on the
  parent when its refined child completes. The wizard polls the parent
  and, when this is non-NULL, follows it to fetch the refined render's
  ``download_url``. Self-FK with ``ON DELETE SET NULL`` so deleting
  the child doesn't cascade-delete the parent (chain breaks gracefully).

* ``refined_from_render_job_id UUID NULL`` — back pointer set on the
  child to its parent. Powers the cascade-idempotency guard: when the
  refined child's own completion callback fires, the post-render hook
  sees ``refined_from_render_job_id IS NOT NULL`` and short-circuits
  rather than recursively refining a refinement.

* ``refinement_source TEXT NULL`` — provenance for the current row's
  ``input_spec.subtitles``. CHECK-constrained to ``{'whisper', 'manual_edit'}``.
  ``manual_edit`` blocks future Whisper passes; ``whisper`` marks
  refined children. ``NULL`` means "untouched / default
  speaker_transcript timing" — the common state for canonical rows.

Plus one partial index ``ix_shorts_render_jobs_replaced_by`` on
``replaced_by_render_job_id WHERE replaced_by_render_job_id IS NOT NULL``.
Drives the in-service idempotency guard ("has this parent already been
refined?") without bloating writes for the common no-refinement case.

CHECK rather than a Postgres ENUM type follows the precedent set by
migration 055 — sidesteps the
``ENUM-add-value-needs-transaction-per-migration`` footgun
(``feedback_alembic_enum_add_value_pattern.md``) and keeps adding new
provenance values (e.g. ``'gpt-4o-transcribe'`` if we adopt that model
later) a one-line constraint update.

Strictly additive: every new column is nullable, every existing row
keeps NULL for all three columns. No backfill. No row touches.

Revision ID: 056_add_render_refinement_chain
Revises: 055_add_enumeration_source
Create Date: 2026-05-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "056_add_render_refinement_chain"
down_revision: str | None = "055_add_enumeration_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CHECK_CONSTRAINT_NAME = "ck_shorts_render_jobs_refinement_source"
_REPLACED_BY_INDEX_NAME = "ix_shorts_render_jobs_replaced_by"
_ALLOWED_SOURCES = ("whisper", "manual_edit")


def upgrade() -> None:
    # Three additive columns. All nullable, no defaults — every existing
    # row stays NULL on each new column with no backfill required.
    op.add_column(
        "shorts_render_jobs",
        sa.Column(
            "replaced_by_render_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "shorts_render_jobs.id",
                ondelete="SET NULL",
                name="fk_shorts_render_jobs_replaced_by",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "shorts_render_jobs",
        sa.Column(
            "refined_from_render_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "shorts_render_jobs.id",
                ondelete="SET NULL",
                name="fk_shorts_render_jobs_refined_from",
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "shorts_render_jobs",
        sa.Column("refinement_source", sa.String(length=32), nullable=True),
    )

    # CHECK constraint locks the allowed provenance values. Pattern
    # mirrors migration 055 — Postgres lacks ``ADD CONSTRAINT IF NOT
    # EXISTS`` for table constraints, so guard with a pg_constraint
    # lookup so the migration is idempotent if interrupted mid-run.
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{_CHECK_CONSTRAINT_NAME}'
            ) THEN
                ALTER TABLE shorts_render_jobs
                    ADD CONSTRAINT {_CHECK_CONSTRAINT_NAME}
                    CHECK (
                        refinement_source IS NULL
                        OR refinement_source IN ('whisper', 'manual_edit')
                    );
            END IF;
        END $$;
    """)

    # Partial index drives the "already refined?" guard. Partial because
    # ~99% of rows are canonical (NULL replaced_by) and we only want
    # the index to track active refinement chains.
    op.create_index(
        _REPLACED_BY_INDEX_NAME,
        "shorts_render_jobs",
        ["replaced_by_render_job_id"],
        unique=False,
        postgresql_where=sa.text(
            "replaced_by_render_job_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    # Reverse order: index → constraint → columns. Each step is
    # idempotent (``IF EXISTS``) so a partial-state downgrade still
    # succeeds.
    op.drop_index(
        _REPLACED_BY_INDEX_NAME,
        table_name="shorts_render_jobs",
        if_exists=True,
    )

    op.execute(f"""
        ALTER TABLE shorts_render_jobs
            DROP CONSTRAINT IF EXISTS {_CHECK_CONSTRAINT_NAME}
    """)

    # Drop columns; their FKs are removed automatically by Postgres
    # when the column goes away.
    op.drop_column("shorts_render_jobs", "refinement_source")
    op.drop_column("shorts_render_jobs", "refined_from_render_job_id")
    op.drop_column("shorts_render_jobs", "replaced_by_render_job_id")
