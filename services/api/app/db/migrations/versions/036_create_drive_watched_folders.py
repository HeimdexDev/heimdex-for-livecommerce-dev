from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision: str = "036_create_drive_watched_folders"
down_revision: str | None = "035_add_org_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _ = op.create_table(
        "drive_watched_folders",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", UUID(as_uuid=True), nullable=False),
        sa.Column("google_folder_id", sa.String(length=256), nullable=False),
        sa.Column("folder_name", sa.String(length=500), nullable=False),
        sa.Column("folder_path", sa.Text(), nullable=True),
        sa.Column("parent_folder_id", sa.String(length=256), nullable=True),
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "content_types",
            ARRAY(sa.String(length=32)),
            nullable=False,
            server_default=sa.text("ARRAY['video']::varchar[]"),
        ),
        sa.Column("file_count_cached", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_enumerated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["drive_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "google_folder_id", name="uq_watched_folders_org_folder"),
    )
    op.create_index("ix_watched_folders_org_id", "drive_watched_folders", ["org_id"], unique=False)
    op.create_index(
        "ix_watched_folders_connection_id",
        "drive_watched_folders",
        ["connection_id"],
        unique=False,
    )
    op.create_index(
        "ix_watched_folders_sync_enabled",
        "drive_watched_folders",
        ["org_id", "sync_enabled"],
        unique=False,
        postgresql_where=sa.text("sync_enabled = true"),
    )
    op.create_index(
        "ix_watched_folders_parent",
        "drive_watched_folders",
        ["org_id", "parent_folder_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_watched_folders_parent", table_name="drive_watched_folders")
    op.drop_index("ix_watched_folders_sync_enabled", table_name="drive_watched_folders")
    op.drop_index("ix_watched_folders_connection_id", table_name="drive_watched_folders")
    op.drop_index("ix_watched_folders_org_id", table_name="drive_watched_folders")
    op.drop_table("drive_watched_folders")
