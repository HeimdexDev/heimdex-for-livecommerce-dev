"""Add auth0_org_id column to orgs table

Stores the Auth0 Organizations identifier so the backend can enforce
token org_id == subdomain org binding.

Revision ID: 007_add_orgs_auth0_org_id
Revises: 006_add_agent_intents_table
Create Date: 2026-02-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "007_add_orgs_auth0_org_id"
down_revision: str | None = "006_add_agent_intents_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orgs",
        sa.Column("auth0_org_id", sa.String(64), nullable=True),
    )
    op.create_index(
        op.f("ix_orgs_auth0_org_id"), "orgs", ["auth0_org_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_orgs_auth0_org_id"), table_name="orgs")
    op.drop_column("orgs", "auth0_org_id")
