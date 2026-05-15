"""
RBAC tests for drive sync endpoints.

Verifies that write endpoints require ADMIN role (return 403 for MEMBER)
and read endpoints are accessible to MEMBER (return 200).

Pattern: override get_current_user and get_current_org dependencies so no
real DB or auth token is needed.  Repository methods are patched to return
minimal mocks so the handler logic beyond the RBAC guard does not fail.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.base import get_db_session
from app.dependencies import (
    get_drive_connection_repository,
    get_drive_file_repository,
    get_drive_secret_repository,
    get_scene_opensearch_client,
    get_watched_folder_repository,
)
from app.modules.auth.service import get_current_user
from app.modules.drive.router import router as drive_router
from app.modules.drive.watched_folder_router import router as watched_folder_router
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import UserRole


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(role: UserRole) -> MagicMock:
    user = MagicMock()
    user.role = role.value
    user.id = uuid4()
    user.org_id = uuid4()
    user.email = f"{role.value}@test.com"
    return user


def _build_app(user: MagicMock) -> FastAPI:
    """Build a minimal FastAPI app with both drive routers and mocked deps."""
    app = FastAPI()
    app.include_router(drive_router, prefix="/api")
    app.include_router(watched_folder_router, prefix="/api")

    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")

    async def _mock_get_current_user():
        return user

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    async def _mock_get_db():
        return AsyncMock()

    async def _mock_conn_repo():
        return AsyncMock()

    async def _mock_file_repo():
        return AsyncMock()

    async def _mock_secret_repo():
        return AsyncMock()

    async def _mock_scene_client():
        return AsyncMock()

    async def _mock_watched_folder_repo():
        return AsyncMock()

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    app.dependency_overrides[get_current_org] = _mock_get_current_org
    app.dependency_overrides[get_db_session] = _mock_get_db
    app.dependency_overrides[get_drive_connection_repository] = _mock_conn_repo
    app.dependency_overrides[get_drive_file_repository] = _mock_file_repo
    app.dependency_overrides[get_drive_secret_repository] = _mock_secret_repo
    app.dependency_overrides[get_scene_opensearch_client] = _mock_scene_client
    app.dependency_overrides[get_watched_folder_repository] = _mock_watched_folder_repo

    return app


def _settings_enabled():
    from types import SimpleNamespace
    return SimpleNamespace(drive_connector_enabled=True)


# ── Write endpoints — MEMBER should receive 403 ───────────────────────────────

class TestWriteEndpointsForbiddenForMember:
    """MEMBER role must not access write (mutating) drive endpoints."""

    def _client(self) -> TestClient:
        return TestClient(_build_app(_make_user(UserRole.MEMBER)))

    def test_post_connections_returns_403(self):
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.post(
                    "/api/drive/connections",
                    json={"drive_id": "drive-123", "drive_name": "My Drive"},
                )
        assert response.status_code == 403

    def test_delete_connection_returns_403(self):
        connection_id = uuid4()
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.delete(f"/api/drive/connections/{connection_id}")
        assert response.status_code == 403

    def test_patch_connection_returns_403(self):
        connection_id = uuid4()
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.patch(
                    f"/api/drive/connections/{connection_id}",
                    json={"drive_name": "Renamed"},
                )
        assert response.status_code == 403

    def test_put_secrets_returns_403(self):
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.put(
                    "/api/drive/secrets",
                    json={"sa_key_json": "{}", "impersonate_email": None},
                )
        assert response.status_code == 403

    def test_post_connections_sync_returns_403(self):
        connection_id = uuid4()
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.post(f"/api/drive/connections/{connection_id}/sync")
        assert response.status_code == 403

    def test_post_folder_connections_returns_403(self):
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.post(
                    "/api/drive/folder-connections",
                    json={
                        "folder_id": "folder-abc",
                        "folder_name": "Videos",
                        "folder_path": "/Videos",
                        "library_id": str(uuid4()),
                    },
                )
        assert response.status_code == 403

    def test_post_enumerate_folders_returns_403(self):
        with patch("app.modules.drive.watched_folder_router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.post("/api/drive/watched-folders/enumerate-folders")
        assert response.status_code == 403

    def test_patch_folder_toggle_returns_403(self):
        folder_id = uuid4()
        with patch("app.modules.drive.watched_folder_router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.patch(
                    f"/api/drive/watched-folders/{folder_id}/toggle",
                    json={"sync_enabled": True},
                )
        assert response.status_code == 403

    def test_patch_folder_content_types_returns_403(self):
        folder_id = uuid4()
        with patch("app.modules.drive.watched_folder_router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.patch(
                    f"/api/drive/watched-folders/{folder_id}/content-types",
                    json={"content_types": ["video"]},
                )
        assert response.status_code == 403


# ── Read endpoints — MEMBER should receive 200 ────────────────────────────────

class TestReadEndpointsAllowedForMember:
    """MEMBER role must be able to access read-only drive endpoints."""

    def _client(self) -> TestClient:
        return TestClient(_build_app(_make_user(UserRole.MEMBER)))

    def test_get_status_returns_200(self):
        with (
            patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()),
            patch(
                "app.modules.drive.repository.DriveConnectionRepository.list_by_org",
                AsyncMock(return_value=[]),
            ),
        ):
            with self._client() as client:
                response = client.get("/api/drive/status")
        # drive disabled path returns 200 with connected=False;
        # with drive enabled but no connections it also returns 200
        assert response.status_code == 200

    def test_get_connections_returns_200(self):
        with (
            patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()),
            patch(
                "app.modules.drive.repository.DriveConnectionRepository.list_by_org",
                AsyncMock(return_value=[]),
            ),
        ):
            with self._client() as client:
                response = client.get("/api/drive/connections")
        assert response.status_code == 200

    def test_get_watched_folders_returns_200(self):
        # _require_drive_enabled is defined in drive.router and imported into
        # watched_folder_router, so the patch target is drive.router.get_settings.
        with (
            patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()),
            patch(
                "app.modules.drive.repository.DriveConnectionRepository.list_by_org",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.modules.drive.watched_folder_repository.WatchedFolderRepository.list_by_org",
                AsyncMock(return_value=[]),
            ),
        ):
            with self._client() as client:
                response = client.get("/api/drive/watched-folders")
        assert response.status_code == 200


# ── Admin can access write endpoints ─────────────────────────────────────────

class TestWriteEndpointsAllowedForAdmin:
    """ADMIN role must not be blocked by the RBAC guard on write endpoints.

    We only check that the guard itself passes (no 403).  The handler may
    return 4xx for other reasons (missing data, disabled feature) — those are
    not RBAC failures.
    """

    def _client(self) -> TestClient:
        return TestClient(_build_app(_make_user(UserRole.ADMIN)))

    def test_post_connections_not_403_for_admin(self):
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.post(
                    "/api/drive/connections",
                    json={"drive_id": "drive-123", "drive_name": "My Drive"},
                )
        assert response.status_code != 403

    def test_put_secrets_not_403_for_admin(self):
        with patch("app.modules.drive.router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.put(
                    "/api/drive/secrets",
                    json={"sa_key_json": "{}", "impersonate_email": None},
                )
        assert response.status_code != 403

    def test_post_enumerate_folders_not_403_for_admin(self):
        with patch("app.modules.drive.watched_folder_router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.post("/api/drive/watched-folders/enumerate-folders")
        assert response.status_code != 403

    def test_patch_folder_toggle_not_403_for_admin(self):
        folder_id = uuid4()
        with patch("app.modules.drive.watched_folder_router.get_settings", return_value=_settings_enabled()):
            with self._client() as client:
                response = client.patch(
                    f"/api/drive/watched-folders/{folder_id}/toggle",
                    json={"sync_enabled": True},
                )
        assert response.status_code != 403
