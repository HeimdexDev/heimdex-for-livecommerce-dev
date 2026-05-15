from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_scene_opensearch_client
from app.db.base import get_db_session
from app.modules.auth.service import get_current_user
from app.modules.drive.router import router as drive_router
from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org


def _settings(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(drive_connector_enabled=enabled)


def _make_connection() -> MagicMock:
    conn = MagicMock()
    conn.id = uuid4()
    conn.org_id = uuid4()
    conn.sync_requested_at = None
    return conn


def _build_drive_app(
    db: AsyncMock,
    org_ctx: OrgContext,
    scene_client: AsyncMock | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(drive_router, prefix="/api")

    async def _mock_get_db_session():
        return db

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    async def _mock_scene_client() -> AsyncMock:
        return scene_client or AsyncMock()

    async def _mock_current_user() -> SimpleNamespace:
        return SimpleNamespace(role="admin")

    app.dependency_overrides[get_db_session] = _mock_get_db_session
    app.dependency_overrides[get_current_org] = _mock_get_current_org
    app.dependency_overrides[get_current_user] = _mock_current_user
    app.dependency_overrides[get_scene_opensearch_client] = _mock_scene_client
    return app


def test_trigger_sync_sets_flag():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)

    connection_id = uuid4()
    conn = _make_connection()
    conn.sync_requested_at = datetime(2026, 2, 22, 10, 20, 30, tzinfo=timezone.utc)

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "set_sync_requested",
            AsyncMock(return_value=conn),
        ) as mock_set_sync,
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/drive/connections/{connection_id}/sync",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "requested"
    assert payload["sync_requested_at"] == "2026-02-22T10:20:30Z"
    mock_set_sync.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_trigger_sync_connection_not_found():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "set_sync_requested",
            AsyncMock(return_value=None),
        ),
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/drive/connections/{connection_id}/sync",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "Connection not found"


def test_trigger_sync_drive_disabled():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(False)),
        patch.object(DriveConnectionRepository, "set_sync_requested", AsyncMock()) as mock_set_sync,
    ):
        with TestClient(app) as client:
            response = client.post(
                f"/api/drive/connections/{uuid4()}/sync",
                headers={"host": "testorg.app.heimdex.local"},
            )

    assert response.status_code == 404
    assert response.json()["detail"] == "Drive connector is not enabled"
    mock_set_sync.assert_not_awaited()
    app.dependency_overrides.clear()


def test_delete_connection_cascade_soft_deletes_files():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    scene_client.delete_scenes_by_video_id = AsyncMock(return_value=3)
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()
    conn = _make_connection()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "get_by_id",
            AsyncMock(return_value=conn),
        ),
        patch.object(
            DriveConnectionRepository,
            "delete",
            AsyncMock(return_value=True),
        ) as mock_delete_conn,
        patch.object(
            DriveFileRepository,
            "soft_delete_by_connection",
            AsyncMock(return_value=["vid_1", "vid_2", "vid_3"]),
        ) as mock_soft_delete,
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 204
    mock_soft_delete.assert_awaited_once_with(connection_id, org_ctx.org_id)
    assert scene_client.delete_scenes_by_video_id.await_count == 3
    mock_delete_conn.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_delete_connection_cascade_removes_scenes():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    scene_client.delete_scenes_by_video_id = AsyncMock(return_value=5)
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()
    conn = _make_connection()
    video_ids = ["vid_a", "vid_b"]

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveConnectionRepository,
            "delete",
            AsyncMock(return_value=True),
        ) as mock_delete_conn,
        patch.object(
            DriveFileRepository,
            "soft_delete_by_connection",
            AsyncMock(return_value=video_ids),
        ),
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 204
    expected_calls = [
        ((str(org_ctx.org_id), "vid_a"),),
        ((str(org_ctx.org_id), "vid_b"),),
    ]
    actual_calls = [call.args for call in scene_client.delete_scenes_by_video_id.await_args_list]
    assert actual_calls == [c[0] for c in expected_calls]
    mock_delete_conn.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_delete_connection_removes_record():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    scene_client.delete_scenes_by_video_id = AsyncMock(return_value=1)
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()
    conn = _make_connection()
    conn.status = "active"

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveConnectionRepository,
            "delete",
            AsyncMock(return_value=True),
        ) as mock_delete_conn,
        patch.object(
            DriveFileRepository,
            "soft_delete_by_connection",
            AsyncMock(return_value=["vid_1"]),
        ),
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 204
    mock_delete_conn.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_delete_connection_not_found_returns_404():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=None)),
        patch.object(DriveFileRepository, "soft_delete_by_connection", AsyncMock()) as mock_soft_delete,
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "Connection not found"
    mock_soft_delete.assert_not_awaited()


def test_delete_connection_wrong_org_returns_404():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=None)),
        patch.object(DriveFileRepository, "soft_delete_by_connection", AsyncMock()) as mock_soft_delete,
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "Connection not found"
    mock_soft_delete.assert_not_awaited()


def test_delete_connection_no_files():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    scene_client.delete_scenes_by_video_id = AsyncMock(return_value=0)
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()
    conn = _make_connection()
    conn.status = "active"

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveConnectionRepository,
            "delete",
            AsyncMock(return_value=True),
        ) as mock_delete_conn,
        patch.object(
            DriveFileRepository,
            "soft_delete_by_connection",
            AsyncMock(return_value=[]),
        ),
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 204
    scene_client.delete_scenes_by_video_id.assert_not_awaited()
    mock_delete_conn.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_delete_connection_already_deleted_files_skipped():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    scene_client.delete_scenes_by_video_id = AsyncMock(return_value=2)
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()
    conn = _make_connection()
    conn.status = "active"

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveConnectionRepository,
            "delete",
            AsyncMock(return_value=True),
        ) as mock_delete_conn,
        patch.object(
            DriveFileRepository,
            "soft_delete_by_connection",
            AsyncMock(return_value=["vid_live_1", "vid_live_2"]),
        ),
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 204
    assert scene_client.delete_scenes_by_video_id.await_count == 2
    called_video_ids = [call.args[1] for call in scene_client.delete_scenes_by_video_id.await_args_list]
    assert called_video_ids == ["vid_live_1", "vid_live_2"]
    mock_delete_conn.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_delete_connection_opensearch_failure_doesnt_block():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    scene_client = AsyncMock()
    scene_client.delete_scenes_by_video_id = AsyncMock(side_effect=RuntimeError("opensearch down"))
    app = _build_drive_app(db, org_ctx, scene_client=scene_client)

    connection_id = uuid4()
    conn = _make_connection()
    conn.status = "active"

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveConnectionRepository,
            "delete",
            AsyncMock(return_value=True),
        ) as mock_delete_conn,
        patch.object(
            DriveFileRepository,
            "soft_delete_by_connection",
            AsyncMock(return_value=["vid_1"]),
        ),
        patch("app.modules.drive.router.logger.warning") as mock_warning,
    ):
        with TestClient(app) as client:
            response = client.delete(
                f"/api/drive/connections/{connection_id}",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 204
    mock_delete_conn.assert_awaited_once_with(connection_id, org_ctx.org_id)
    mock_warning.assert_called_once()


def test_list_folders_empty():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()
    conn = _make_connection()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "get_by_id",
            AsyncMock(return_value=conn),
        ),
        patch.object(
            DriveFileRepository,
            "get_folder_stats",
            AsyncMock(return_value=[]),
        ) as mock_get_folder_stats,
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"folders": [], "total_files": 0}
    mock_get_folder_stats.assert_awaited_once_with(connection_id, org_ctx.org_id)


def test_list_folders_groups_by_path():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()
    conn = _make_connection()

    folder_stats = [
        {
            "folder_path": "Meeting Videos/2026-02",
            "file_count": 3,
            "indexed_count": 1,
            "processing_count": 1,
            "failed_count": 0,
            "pending_count": 1,
        },
        {
            "folder_path": "쇼츠",
            "file_count": 2,
            "indexed_count": 2,
            "processing_count": 0,
            "failed_count": 0,
            "pending_count": 0,
        },
    ]

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveFileRepository,
            "get_folder_stats",
            AsyncMock(return_value=folder_stats),
        ),
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 5
    assert len(payload["folders"]) == 2
    assert payload["folders"][0]["folder_path"] == "Meeting Videos/2026-02"
    assert payload["folders"][1]["folder_path"] == "쇼츠"


def test_list_folders_null_path_grouped():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()
    conn = _make_connection()

    folder_stats = [
        {
            "folder_path": "(루트)",
            "file_count": 4,
            "indexed_count": 2,
            "processing_count": 1,
            "failed_count": 0,
            "pending_count": 1,
        }
    ]

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(DriveConnectionRepository, "get_by_id", AsyncMock(return_value=conn)),
        patch.object(
            DriveFileRepository,
            "get_folder_stats",
            AsyncMock(return_value=folder_stats),
        ),
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_files"] == 4
    assert payload["folders"][0]["folder_path"] == "(루트)"


def test_list_folders_connection_not_found():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    db = AsyncMock()
    app = _build_drive_app(db, org_ctx)
    connection_id = uuid4()

    with (
        patch("app.modules.drive.router.get_settings", return_value=_settings(True)),
        patch.object(
            DriveConnectionRepository,
            "get_by_id",
            AsyncMock(return_value=None),
        ),
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/api/drive/connections/{connection_id}/folders",
                headers={"host": "testorg.app.heimdex.local"},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "Connection not found"
