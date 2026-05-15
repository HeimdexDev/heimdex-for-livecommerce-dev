"""Add agent_api_key column to orgs table

Revision ID: 003_add_org_agent_api_key
Revises: 002_add_auth0_sub
Create Date: 2026-02-15

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_add_org_agent_api_key"
down_revision: str | None = "002_add_auth0_sub"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orgs",
        sa.Column("agent_api_key", sa.String(255), nullable=True),
    )
    op.create_index("ix_orgs_agent_api_key", "orgs", ["agent_api_key"])


def downgrade() -> None:
    op.drop_index("ix_orgs_agent_api_key", table_name="orgs")
    op.drop_column("orgs", "agent_api_key")
