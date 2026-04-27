"""Create worker_events partitioned table for worker observability

Revision ID: 049_create_worker_events
Revises: 048_add_blur_masks_and_exports
Create Date: 2026-04-20

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "049_create_worker_events"
down_revision: str | None = "048_add_blur_masks_and_exports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE worker_events (
            id           BIGSERIAL    NOT NULL,
            service      TEXT         NOT NULL,
            event_name   TEXT         NOT NULL,
            category     TEXT         NOT NULL,
            level        TEXT         NOT NULL,
            org_id       UUID,
            job_id       UUID,
            video_id     UUID,
            duration_ms  INTEGER,
            message      TEXT,
            metadata     JSONB        NOT NULL DEFAULT '{}',
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )

    op.execute("CREATE INDEX ix_worker_events_service ON worker_events (service)")
    op.execute("CREATE INDEX ix_worker_events_category ON worker_events (category)")
    op.execute("CREATE INDEX ix_worker_events_level ON worker_events (level)")

    op.execute(
        "CREATE INDEX ix_worker_events_time_brin "
        "ON worker_events USING BRIN (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS worker_events CASCADE")
