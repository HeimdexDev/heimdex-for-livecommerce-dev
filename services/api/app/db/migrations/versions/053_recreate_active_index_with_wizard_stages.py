"""Recreate ix_product_scan_jobs_active with the wizard's new active stages.

Hotfix split from migration 052 — Postgres rejects using
``ALTER TYPE … ADD VALUE``-added enum members in the same transaction
that added them. The partial-index ``WHERE stage IN
('preview_ready','fanned_out',…)`` predicate triggered
``UnsafeNewEnumValueUsage`` on every staging deploy after PR #114
merged (17-hour blast radius — staging stuck at revision 051 the
whole time before this fix landed).

Splitting the index into a separate migration lets it run in a
fresh transaction where the new enum values are already-committed
members of the type. ``IF NOT EXISTS`` on the create + DROP guards
keep this idempotent across re-runs.

The OLD ``ix_product_scan_jobs_active`` (scoped to the original
active stages, no mode filter) survives unchanged after migration
052 — this migration replaces it with the wizard-aware shape:

  * Includes the new active stages: ``preview_ready``, ``fanned_out``
  * Excludes ``mode='render_child'`` so the per-org concurrency cap
    counts parents only (children don't take a cap slot)

Plan: ``.claude/plans/shorts-auto-product-v2-phase-4-7.md`` §3.

Revision ID: 053_recreate_active_index_with_wizard_stages
Revises: 052_extend_scan_jobs_for_wizard
Create Date: 2026-05-03

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "053_recreate_active_index_with_wizard_stages"
down_revision: str | None = "052_extend_scan_jobs_for_wizard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the legacy active-index (created in 051) — it pre-dates the
    # mode discriminator and includes ``mode='render_child'`` rows in
    # its count, which would inflate the wizard's per-org concurrency
    # cap reading.
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_active")
    # Rebuild with the wizard-aware predicate. Safe to use the new
    # enum values here because migration 052 committed them in its
    # own transaction.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_product_scan_jobs_active
            ON product_scan_jobs(org_id, stage)
            WHERE stage IN (
                'queued','enumerating','tracking','assembling','rendering',
                'preview_ready','fanned_out'
            ) AND mode <> 'render_child'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_active")
    # Restore the original active-only index shape from migration 051
    # (no mode filter, original stage set).
    op.execute("""
        CREATE INDEX ix_product_scan_jobs_active
            ON product_scan_jobs(org_id, stage)
            WHERE stage IN (
                'queued','enumerating','tracking','assembling','rendering'
            )
    """)
