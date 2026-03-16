"""Add settings JSONB column to orgs table.

Revision ID: 035_add_org_settings
Revises: 034_create_scene_reprocess_jobs
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "035_add_org_settings"
down_revision = "034_create_scene_reprocess_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orgs",
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("orgs", "settings")
