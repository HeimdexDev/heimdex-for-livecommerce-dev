"""Add unique constraint on (org_id, email) to users table

Prevents duplicate email addresses within the same organization,
which could otherwise lead to ambiguous Auth0 auto-linking.

Revision ID: 008_add_users_email_unique_per_org
Revises: 007_add_orgs_auth0_org_id
Create Date: 2026-02-16
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "008_add_users_email_unique_per_org"
down_revision: str | None = "007_add_orgs_auth0_org_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_users_org_id_email", "users", ["org_id", "email"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_users_org_id_email", "users", type_="unique")
