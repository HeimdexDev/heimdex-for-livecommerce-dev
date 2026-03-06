"""Create search_events partitioned table for search analytics

Revision ID: 031_create_search_events
Revises: 030_create_people_video_exclusions
Create Date: 2026-03-07

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "031_create_search_events"
down_revision: str | None = "030_create_people_video_exclusions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create the parent partitioned table.
    # Alembic's op.create_table doesn't support PARTITION BY, so use raw DDL.
    op.execute(
        """
        CREATE TABLE search_events (
            id          BIGSERIAL       NOT NULL,
            org_id      UUID            NOT NULL,
            user_id     UUID            NOT NULL,
            query_text  TEXT            NOT NULL,
            search_mode TEXT            NOT NULL,
            result_count INTEGER,
            response_ms  INTEGER,
            metadata    JSONB           NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
        """
    )

    # B-tree on (org_id, created_at DESC) — most common analytics query pattern
    op.execute(
        "CREATE INDEX ix_search_events_org_time "
        "ON search_events (org_id, created_at DESC)"
    )

    # BRIN on created_at — compact index for time-range scans on partitioned data
    op.execute(
        "CREATE INDEX ix_search_events_time_brin "
        "ON search_events USING BRIN (created_at)"
    )


def downgrade() -> None:
    # Dropping the parent cascades to all partitions
    op.execute("DROP TABLE IF EXISTS search_events CASCADE")
