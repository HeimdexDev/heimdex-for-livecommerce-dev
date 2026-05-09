"""Widen ix_product_scan_jobs_child_queue to cover expired-lease render_child rows.

Self-healing runner (PR 3 of the cap-stuck plan) polls a wider WHERE
predicate so render_child rows orphaned by an API restart can be
re-claimed once their lease elapses past
``LEASE_RECLAIM_GRACE_SECONDS``. Without this index update the wider
poll falls back to a sequential scan over ``product_scan_jobs``.

Plan: ``.claude/plans/shorts-auto-product-cap-stuck-fix.md`` (PR 3 of 3).

Predicate widens FROM:

    mode = 'render_child' AND stage = 'queued'

TO:

    mode = 'render_child'
    AND (
        stage = 'queued'
        OR (stage IN ('assembling','rendering')
            AND lease_expires_at IS NOT NULL)
    )

The new predicate is a strict superset of the old. Backward-compatible:
existing queued-only callers (``find_queued_render_children``, the
flag-off legacy shim) still hit the index correctly — partial-index
predicate matches its filter superset trivially.

Idempotent via ``IF EXISTS`` / ``IF NOT EXISTS`` on both sides. Runs in
the migration's own transaction (``transaction_per_migration=True`` in
``env.py``) — at the staging+prod row scale (~hundreds), regular
``CREATE INDEX`` is microseconds and locks the table only briefly. We
intentionally don't use ``CONCURRENTLY`` here: that requires
``autocommit_block``, doesn't match the repo convention (see migration
053), and would be over-engineering at this scale.

Revision ID: 058_widen_child_queue_index_for_self_heal
Revises: 057_add_render_idempotency_key
Create Date: 2026-05-10
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "058_widen_child_queue_index_for_self_heal"
down_revision: str | None = "057_add_render_idempotency_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_child_queue")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_product_scan_jobs_child_queue
            ON product_scan_jobs (created_at)
            WHERE mode = 'render_child'
              AND (
                  stage = 'queued'
                  OR (stage IN ('assembling','rendering')
                      AND lease_expires_at IS NOT NULL)
              )
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_scan_jobs_child_queue")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_product_scan_jobs_child_queue
            ON product_scan_jobs (created_at)
            WHERE mode = 'render_child' AND stage = 'queued'
    """)
