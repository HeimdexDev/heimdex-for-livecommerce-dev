"""
Tests for migration 036_add_shorts_render_jobs_table.

Verifies the migration module structure, column definitions,
indexes, and foreign keys without requiring a live database.
"""
from __future__ import annotations

import importlib
import types
from unittest.mock import MagicMock, call, patch

import pytest


@pytest.fixture
def migration_module() -> types.ModuleType:
    """Import the migration module."""
    return importlib.import_module(
        "app.db.migrations.versions.036_add_shorts_render_jobs_table"
    )


class TestMigrationMetadata:
    def test_revision_id(self, migration_module: types.ModuleType) -> None:
        assert migration_module.revision == "036_add_shorts_render_jobs_table"

    def test_down_revision(self, migration_module: types.ModuleType) -> None:
        assert migration_module.down_revision == "035_add_org_settings"

    def test_branch_labels_none(self, migration_module: types.ModuleType) -> None:
        assert migration_module.branch_labels is None

    def test_depends_on_none(self, migration_module: types.ModuleType) -> None:
        assert migration_module.depends_on is None


class TestUpgrade:
    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_creates_table_with_correct_name(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.upgrade()
        create_table_call = mock_op.create_table.call_args
        assert create_table_call[0][0] == "shorts_render_jobs"

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_table_has_15_columns(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        """Verify exactly 15 columns + 1 PK + 2 FK constraints = 18 positional args after table name."""
        mock_op.f = lambda x: x
        migration_module.upgrade()
        create_table_call = mock_op.create_table.call_args
        # args[0] is table name, rest are columns and constraints
        # 15 columns + PK + 2 FK = 18
        non_name_args = create_table_call[0][1:]
        assert len(non_name_args) == 18

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_creates_5_indexes(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.upgrade()
        assert mock_op.create_index.call_count == 5

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_index_names(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.upgrade()
        index_names = [c[0][0] for c in mock_op.create_index.call_args_list]
        expected = [
            "ix_shorts_render_jobs_org_id",
            "ix_shorts_render_jobs_user_id",
            "ix_shorts_render_jobs_org_id_user_id",
            "ix_shorts_render_jobs_status",
            "ix_shorts_render_jobs_expires_at",
        ]
        assert index_names == expected

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_all_indexes_on_correct_table(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.upgrade()
        for c in mock_op.create_index.call_args_list:
            assert c[0][1] == "shorts_render_jobs"

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_composite_index_columns(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.upgrade()
        composite_call = mock_op.create_index.call_args_list[2]
        assert composite_call[0][2] == ["org_id", "user_id"]

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_status_index_column(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.upgrade()
        status_call = mock_op.create_index.call_args_list[3]
        assert status_call[0][2] == ["status"]

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_expires_at_index_column(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.upgrade()
        expires_call = mock_op.create_index.call_args_list[4]
        assert expires_call[0][2] == ["expires_at"]


class TestDowngrade:
    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_drops_5_indexes(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.downgrade()
        assert mock_op.drop_index.call_count == 5

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_drops_table(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        mock_op.f = lambda x: x
        migration_module.downgrade()
        mock_op.drop_table.assert_called_once_with("shorts_render_jobs")

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_drops_indexes_before_table(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        """Indexes must be dropped before the table."""
        mock_op.f = lambda x: x
        call_order: list[str] = []
        mock_op.drop_index.side_effect = lambda *a, **kw: call_order.append("drop_index")
        mock_op.drop_table.side_effect = lambda *a, **kw: call_order.append("drop_table")
        migration_module.downgrade()
        assert call_order == ["drop_index"] * 5 + ["drop_table"]

    @patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op")
    def test_drop_index_names_match_create(self, mock_op: MagicMock, migration_module: types.ModuleType) -> None:
        """Downgrade should drop the same index names that upgrade creates."""
        mock_op.f = lambda x: x
        migration_module.downgrade()
        dropped_names = [c[0][0] for c in mock_op.drop_index.call_args_list]
        expected = [
            "ix_shorts_render_jobs_expires_at",
            "ix_shorts_render_jobs_status",
            "ix_shorts_render_jobs_org_id_user_id",
            "ix_shorts_render_jobs_user_id",
            "ix_shorts_render_jobs_org_id",
        ]
        assert dropped_names == expected


class TestColumnDefinitions:
    """Verify column types and constraints by inspecting the create_table call."""

    @pytest.fixture
    def columns(self, migration_module: types.ModuleType) -> dict:
        """Extract column definitions from the create_table call."""
        import sqlalchemy as sa

        with patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op") as mock_op:
            mock_op.f = lambda x: x
            migration_module.upgrade()

        create_args = mock_op.create_table.call_args[0][1:]  # skip table name
        cols = {}
        for arg in create_args:
            if isinstance(arg, sa.Column):
                cols[arg.name] = arg
        return cols

    def test_id_is_uuid(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["id"].type, sa.UUID)
        assert columns["id"].nullable is False

    def test_org_id_is_uuid(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["org_id"].type, sa.UUID)
        assert columns["org_id"].nullable is False

    def test_user_id_is_uuid(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["user_id"].type, sa.UUID)
        assert columns["user_id"].nullable is False

    def test_video_id_is_string(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["video_id"].type, sa.String)
        assert columns["video_id"].nullable is False

    def test_title_is_nullable_string(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["title"].type, sa.String)
        assert columns["title"].nullable is True

    def test_status_default_queued(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["status"].type, sa.String)
        assert columns["status"].nullable is False
        assert columns["status"].server_default is not None

    def test_input_spec_is_jsonb(self, columns: dict) -> None:
        from sqlalchemy.dialects.postgresql import JSONB
        assert isinstance(columns["input_spec"].type, JSONB)
        assert columns["input_spec"].nullable is False

    def test_output_s3_key_nullable(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["output_s3_key"].type, sa.String)
        assert columns["output_s3_key"].nullable is True

    def test_output_duration_ms_nullable(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["output_duration_ms"].type, sa.Integer)
        assert columns["output_duration_ms"].nullable is True

    def test_output_size_bytes_is_bigint(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["output_size_bytes"].type, sa.BigInteger)
        assert columns["output_size_bytes"].nullable is True

    def test_error_is_text(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["error"].type, sa.Text)
        assert columns["error"].nullable is True

    def test_render_time_ms_nullable(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["render_time_ms"].type, sa.Integer)
        assert columns["render_time_ms"].nullable is True

    def test_created_at_has_server_default(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["created_at"].type, sa.DateTime)
        assert columns["created_at"].type.timezone is True
        assert columns["created_at"].nullable is False
        assert columns["created_at"].server_default is not None

    def test_completed_at_nullable(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["completed_at"].type, sa.DateTime)
        assert columns["completed_at"].nullable is True

    def test_expires_at_nullable(self, columns: dict) -> None:
        import sqlalchemy as sa
        assert isinstance(columns["expires_at"].type, sa.DateTime)
        assert columns["expires_at"].nullable is True

    def test_has_all_15_columns(self, columns: dict) -> None:
        expected_columns = {
            "id", "org_id", "user_id", "video_id", "title", "status",
            "input_spec", "output_s3_key", "output_duration_ms",
            "output_size_bytes", "error", "render_time_ms",
            "created_at", "completed_at", "expires_at",
        }
        assert set(columns.keys()) == expected_columns


class TestForeignKeys:
    """Verify foreign key constraints."""

    @pytest.fixture
    def constraints(self, migration_module: types.ModuleType) -> list:
        import sqlalchemy as sa

        with patch("app.db.migrations.versions.036_add_shorts_render_jobs_table.op") as mock_op:
            mock_op.f = lambda x: x
            migration_module.upgrade()

        create_args = mock_op.create_table.call_args[0][1:]
        return [
            arg for arg in create_args
            if isinstance(arg, sa.ForeignKeyConstraint)
        ]

    def test_has_two_foreign_keys(self, constraints: list) -> None:
        assert len(constraints) == 2

    def test_org_id_fk_cascades(self, constraints: list) -> None:
        org_fk = next(c for c in constraints if c.columns == ["org_id"])
        assert org_fk.ondelete == "CASCADE"
        assert list(org_fk.referred_columns) == ["orgs.id"]

    def test_user_id_fk_cascades(self, constraints: list) -> None:
        user_fk = next(c for c in constraints if c.columns == ["user_id"])
        assert user_fk.ondelete == "CASCADE"
        assert list(user_fk.referred_columns) == ["users.id"]
