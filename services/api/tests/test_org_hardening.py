"""
Structural tests for org table hardening.

Verify database-level constraints that enforce multi-tenant isolation:
slug uniqueness, auth0_org_id uniqueness, FK integrity, and startup
validation when Auth0 is enabled.

Run with: pytest tests/test_org_hardening.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestOrgModelConstraints:

    def test_slug_unique_constraint(self):
        from app.modules.orgs.models import Org
        col = Org.__table__.columns["slug"]
        assert col.unique is True

    def test_slug_indexed(self):
        from app.modules.orgs.models import Org
        col = Org.__table__.columns["slug"]
        assert col.index is True

    def test_auth0_org_id_unique_constraint(self):
        from app.modules.orgs.models import Org
        col = Org.__table__.columns["auth0_org_id"]
        assert col.unique is True

    def test_auth0_org_id_nullable(self):
        from app.modules.orgs.models import Org
        col = Org.__table__.columns["auth0_org_id"]
        assert col.nullable is True

    def test_auth0_org_id_indexed(self):
        from app.modules.orgs.models import Org
        col = Org.__table__.columns["auth0_org_id"]
        assert col.index is True


class TestForeignKeyIntegrity:

    @pytest.mark.parametrize("model_path,table_name", [
        ("app.modules.users.models.User", "users"),
        ("app.modules.libraries.models.Library", "libraries"),
        ("app.modules.profiles.models.LibraryProfile", "library_profiles"),
        ("app.modules.devices.models.Device", "devices"),
        ("app.modules.agent_intents.models.AgentIntent", "agent_intents"),
        ("app.modules.people.models.DriveNicknameRegistry", "drive_nickname_registry"),
        ("app.modules.people.models.PeopleClusterLabel", "people_cluster_labels"),
    ])
    def test_org_id_fk_to_orgs(self, model_path, table_name):
        """org_id column must have a foreign key to orgs.id."""
        import importlib
        module_path, class_name = model_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        model = getattr(module, class_name)

        table = model.__table__
        org_id_col = table.columns["org_id"]
        fk_targets = [fk.target_fullname for fk in org_id_col.foreign_keys]
        assert "orgs.id" in fk_targets, f"{table_name}.org_id missing FK to orgs.id"

    @pytest.mark.parametrize("model_path,table_name", [
        ("app.modules.users.models.User", "users"),
        ("app.modules.libraries.models.Library", "libraries"),
        ("app.modules.profiles.models.LibraryProfile", "library_profiles"),
        ("app.modules.devices.models.Device", "devices"),
        ("app.modules.agent_intents.models.AgentIntent", "agent_intents"),
        ("app.modules.people.models.DriveNicknameRegistry", "drive_nickname_registry"),
        ("app.modules.people.models.PeopleClusterLabel", "people_cluster_labels"),
    ])
    def test_org_id_indexed(self, model_path, table_name):
        """org_id column must be indexed for query performance."""
        import importlib
        module_path, class_name = model_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        model = getattr(module, class_name)

        col = model.__table__.columns["org_id"]
        assert col.index is True, f"{table_name}.org_id missing index"


class TestStartupOrgValidation:

    @pytest.mark.asyncio
    async def test_rejects_startup_when_orgs_missing_auth0_org_id(self):
        """App must refuse to start if any org lacks auth0_org_id while Auth0 is enabled."""
        from app.main import _verify_org_auth0_bindings

        mock_engine = MagicMock()
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("acme",), ("badorg",)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.main.async_sessionmaker", return_value=lambda: mock_session_ctx):
            with pytest.raises(SystemExit) as exc_info:
                await _verify_org_auth0_bindings(mock_engine)
            assert "acme" in str(exc_info.value)
            assert "badorg" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_passes_when_all_orgs_have_auth0_org_id(self):
        """Startup succeeds when every org has auth0_org_id."""
        from app.main import _verify_org_auth0_bindings

        mock_engine = MagicMock()
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.main.async_sessionmaker", return_value=lambda: mock_session_ctx):
            await _verify_org_auth0_bindings(mock_engine)

    @pytest.mark.asyncio
    async def test_error_message_lists_all_unbound_slugs(self):
        """Error message must list every org slug missing auth0_org_id."""
        from app.main import _verify_org_auth0_bindings

        mock_engine = MagicMock()
        mock_session = AsyncMock()

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("org-a",), ("org-b",), ("org-c",)]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.main.async_sessionmaker", return_value=lambda: mock_session_ctx):
            with pytest.raises(SystemExit) as exc_info:
                await _verify_org_auth0_bindings(mock_engine)
            detail = str(exc_info.value)
            assert "org-a" in detail
            assert "org-b" in detail
            assert "org-c" in detail
            assert "3 org(s)" in detail
