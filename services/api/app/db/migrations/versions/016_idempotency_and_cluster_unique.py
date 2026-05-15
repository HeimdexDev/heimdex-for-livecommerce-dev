"""Add persistent idempotency table and unique constraint on people_cluster_labels

Revision ID: 016_idempotency_and_cluster_unique
Revises: 015_add_heartbeat_at
Create Date: 2026-02-22

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016_idempotency_and_cluster_unique"
down_revision: str | None = "015_add_heartbeat_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Persistent idempotency store ---
    op.create_table(
        "ingest_idempotency_keys",
        sa.Column("key", sa.String(256), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        comment="Persistent idempotency keys for agent ingest replay protection",
    )
    op.create_index(
        "ix_idempotency_expires_at",
        "ingest_idempotency_keys",
        ["expires_at"],
        unique=False,
    )

    # --- Unique constraint on people_cluster_labels ---
    # Prevents duplicate (org_id, person_cluster_id) rows that can occur
    # when idempotency cache is lost on API restart.
    op.create_unique_constraint(
        "uq_people_cluster_labels_org_person",
        "people_cluster_labels",
        ["org_id", "person_cluster_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_people_cluster_labels_org_person",
        "people_cluster_labels",
        type_="unique",
    )
    op.drop_index("ix_idempotency_expires_at", table_name="ingest_idempotency_keys")
    op.drop_table("ingest_idempotency_keys")
