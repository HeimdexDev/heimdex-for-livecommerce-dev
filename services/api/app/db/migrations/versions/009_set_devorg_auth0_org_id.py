"""Set auth0_org_id for staging org 'devorg'

Binds the devorg record to Auth0 Organization org_V0Y81197qiMgjFFX.
Safe to re-run: only updates if auth0_org_id is currently NULL.

Revision ID: 009_set_devorg_auth0_org_id
Revises: 008_add_users_email_unique_per_org
Create Date: 2026-02-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009_set_devorg_auth0_org_id"
down_revision: str | None = "008_add_users_email_unique_per_org"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEVORG_SLUG = "devorg"
DEVORG_AUTH0_ORG_ID = "org_V0Y81197qiMgjFFX"


def upgrade() -> None:
    orgs = sa.table("orgs", sa.column("slug", sa.String), sa.column("auth0_org_id", sa.String))
    op.execute(
        orgs.update()
        .where(orgs.c.slug == DEVORG_SLUG)
        .where(orgs.c.auth0_org_id.is_(None))
        .values(auth0_org_id=DEVORG_AUTH0_ORG_ID)
    )


def downgrade() -> None:
    orgs = sa.table("orgs", sa.column("slug", sa.String), sa.column("auth0_org_id", sa.String))
    op.execute(
        orgs.update()
        .where(orgs.c.slug == DEVORG_SLUG)
        .where(orgs.c.auth0_org_id == DEVORG_AUTH0_ORG_ID)
        .values(auth0_org_id=None)
    )
