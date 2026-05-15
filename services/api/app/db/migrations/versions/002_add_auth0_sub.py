"""Add auth0_sub column to users table

Revision ID: 002_add_auth0_sub
Revises: 001_initial_schema
Create Date: 2026-02-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002_add_auth0_sub"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth0_sub", sa.String(255), nullable=True),
    )
    op.create_index("ix_users_auth0_sub", "users", ["auth0_sub"])


def downgrade() -> None:
    op.drop_index("ix_users_auth0_sub", table_name="users")
    op.drop_column("users", "auth0_sub")
