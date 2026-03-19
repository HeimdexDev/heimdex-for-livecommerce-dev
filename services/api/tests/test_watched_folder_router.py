from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_db_session, get_scene_opensearch_client, get_watched_folder_repository
from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository
from app.modules.drive.watched_folder_router import router as watched_folder_router
from app.modules.drive.watched_folder_schemas import FolderTreeResponse, ToggleFolderResponse, WatchedFolderResponse
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org


@dataclass
class _FolderModel:
    id: UUID
    google_folder_id: str
    folder_name: str
    folder_path: str | None
    parent_folder_id: str | None
    sync_enabled: bool
    content_types: list[str]
    file_count_cached: int
    connection_id: UUID


@dataclass
class _DriveModel:
    id: UUID
    drive_id: str | None
    drive_name: str | None
    scope_type: str


@dataclass
class _SceneClientMock:
    delete_scenes_by_video_id: AsyncMock


class _FolderRepoMock:
    def __init__(self) -> None:
        self.list_by_org: AsyncMock = AsyncMock(return_value=[])
        self.update_toggle: AsyncMock = AsyncMock(return_value=None)
        self.update_content_types: AsyncMock = AsyncMock(return_value=None)
        self.get_by_id: AsyncMock = AsyncMock(return_value=None)


def _build_watched_folder_app(
    db: AsyncMock,
    org_ctx: OrgContext,
    folder_repo: _FolderRepoMock,
    scene_client: _SceneClientMock | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(watched_folder_router, prefix='/api')

    async def _mock_get_db_session() -> AsyncMock:
        return db

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    def _mock_get_watched_folder_repository() -> _FolderRepoMock:
        return folder_repo

    async def _mock_scene_client() -> object:
        return scene_client or _SceneClientMock(delete_scenes_by_video_id=AsyncMock())

    app.dependency_overrides[get_db_session] = _mock_get_db_session
    app.dependency_overrides[get_current_org] = _mock_get_current_org
    app.dependency_overrides[get_watched_folder_repository] = _mock_get_watched_folder_repository
    app.dependency_overrides[get_scene_opensearch_client] = _mock_scene_client
    return app


def _make_folder(*, sync_enabled: bool, content_types: list[str] | None = None) -> _FolderModel:
    return _FolderModel(
        id=uuid4(),
        google_folder_id='folder-1',
        folder_name='Folder 1',
        folder_path='/Folder 1',
        parent_folder_id=None,
        sync_enabled=sync_enabled,
        content_types=content_types or ['video'],
        file_count_cached=3,
        connection_id=uuid4(),
    )


def _make_drive(*, scope_type: str, drive_id: str | None, drive_name: str | None) -> _DriveModel:
    return _DriveModel(
        id=uuid4(),
        drive_id=drive_id,
        drive_name=drive_name,
        scope_type=scope_type,
    )


def test_get_watched_folders_empty():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveConnectionRepository,
        'list_by_org',
        AsyncMock(return_value=[]),
    ):
        with TestClient(app) as client:
            response = client.get('/api/drive/watched-folders')

    app.dependency_overrides.clear()
    assert response.status_code == 200
    tree = FolderTreeResponse.model_validate(response.json())
    assert tree.folders == []
    assert tree.drives == []


def test_get_watched_folders_with_data():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    folder = _make_folder(sync_enabled=True, content_types=['video', 'image'])
    folder_repo.list_by_org = AsyncMock(return_value=[folder])
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    drives = [
        _make_drive(scope_type='my_drive', drive_id=None, drive_name='My Drive'),
        _make_drive(scope_type='shared_drive', drive_id='drive-1', drive_name='Shared Team'),
    ]

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveConnectionRepository,
        'list_by_org',
        AsyncMock(return_value=drives),
    ):
        with TestClient(app) as client:
            response = client.get('/api/drive/watched-folders')

    app.dependency_overrides.clear()
    assert response.status_code == 200
    tree = FolderTreeResponse.model_validate(response.json())
    assert len(tree.folders) == 1
    assert tree.folders[0].id == folder.id
    assert tree.folders[0].sync_enabled is True
    assert tree.folders[0].content_types == ['video', 'image']
    assert len(tree.drives) == 2
    assert tree.drives[0].connection_id == drives[0].id
    assert tree.drives[0].drive_name == 'My Drive'
    assert tree.drives[1].connection_id == drives[1].id
    assert tree.drives[1].drive_id == 'drive-1'


def test_get_watched_folders_legacy_drive_mapped_to_shared_drive():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    legacy_drive = _make_drive(scope_type='drive', drive_id='sd-1', drive_name='Legacy Shared')

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveConnectionRepository,
        'list_by_org',
        AsyncMock(return_value=[legacy_drive]),
    ):
        with TestClient(app) as client:
            response = client.get('/api/drive/watched-folders')

    app.dependency_overrides.clear()
    assert response.status_code == 200
    tree = FolderTreeResponse.model_validate(response.json())
    assert len(tree.drives) == 1
    assert tree.drives[0].connection_id == legacy_drive.id
    assert tree.drives[0].drive_id == 'sd-1'
    assert tree.drives[0].drive_name == 'Legacy Shared'
    assert tree.drives[0].scope_type == 'shared_drive'


def test_get_watched_folders_deduplicates_legacy_and_new():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    legacy_drive = _make_drive(scope_type='drive', drive_id='sd-1', drive_name='Legacy Name')
    new_drive = _make_drive(scope_type='shared_drive', drive_id='sd-1', drive_name='New Name')

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveConnectionRepository,
        'list_by_org',
        AsyncMock(return_value=[legacy_drive, new_drive]),
    ):
        with TestClient(app) as client:
            response = client.get('/api/drive/watched-folders')

    app.dependency_overrides.clear()
    assert response.status_code == 200
    tree = FolderTreeResponse.model_validate(response.json())
    assert len(tree.drives) == 1
    assert tree.drives[0].connection_id == new_drive.id
    assert tree.drives[0].scope_type == 'shared_drive'


def test_get_watched_folders_excludes_folder_scope_type():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    folder_conn = _make_drive(scope_type='folder', drive_id=None, drive_name=None)
    my_drive = _make_drive(scope_type='my_drive', drive_id=None, drive_name='My Drive')

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveConnectionRepository,
        'list_by_org',
        AsyncMock(return_value=[folder_conn, my_drive]),
    ):
        with TestClient(app) as client:
            response = client.get('/api/drive/watched-folders')

    app.dependency_overrides.clear()
    assert response.status_code == 200
    tree = FolderTreeResponse.model_validate(response.json())
    assert len(tree.drives) == 1
    assert tree.drives[0].scope_type == 'my_drive'


def test_toggle_on():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    updated_folder = _make_folder(sync_enabled=True)
    folder_id = updated_folder.id
    folder_repo.update_toggle = AsyncMock(return_value=updated_folder)
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveConnectionRepository,
        'set_sync_requested',
        AsyncMock(return_value=SimpleNamespace()),
    ) as mock_set_sync:
        with TestClient(app) as client:
            response = client.patch(
                f'/api/drive/watched-folders/{folder_id}/toggle',
                json={'sync_enabled': True},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = ToggleFolderResponse.model_validate(response.json())
    assert payload.folder.id == folder_id
    assert payload.folder.sync_enabled is True
    assert payload.deleted_file_count == 0
    folder_repo.update_toggle.assert_awaited_once_with(folder_id, org_ctx.org_id, True)
    mock_set_sync.assert_awaited_once_with(updated_folder.connection_id, org_ctx.org_id)


def test_toggle_off_calls_scene_deletion():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    updated_folder = _make_folder(sync_enabled=False)
    folder_id = updated_folder.id
    folder_repo.update_toggle = AsyncMock(return_value=updated_folder)
    delete_scenes_by_video_id = AsyncMock(return_value=1)
    scene_client = _SceneClientMock(delete_scenes_by_video_id=delete_scenes_by_video_id)
    app = _build_watched_folder_app(db, org_ctx, folder_repo, scene_client=scene_client)

    video_ids = ['vid-1', 'vid-2']
    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveFileRepository,
        'soft_delete_by_watched_folder',
        AsyncMock(return_value=video_ids),
    ) as mock_soft_delete:
        with TestClient(app) as client:
            response = client.patch(
                f'/api/drive/watched-folders/{folder_id}/toggle',
                json={'sync_enabled': False},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = ToggleFolderResponse.model_validate(response.json())
    assert payload.folder.sync_enabled is False
    assert payload.deleted_file_count == 2
    mock_soft_delete.assert_awaited_once_with(org_ctx.org_id, updated_folder.google_folder_id)
    assert delete_scenes_by_video_id.await_count == 2
    scene_calls = [call.args for call in delete_scenes_by_video_id.await_args_list]
    assert scene_calls == [
        (str(org_ctx.org_id), 'vid-1'),
        (str(org_ctx.org_id), 'vid-2'),
    ]


def test_toggle_404_unknown_folder():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    folder_id = uuid4()
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)), patch.object(
        DriveFileRepository,
        'soft_delete_by_watched_folder',
        AsyncMock(return_value=[]),
    ) as mock_soft_delete:
        with TestClient(app) as client:
            response = client.patch(
                f'/api/drive/watched-folders/{folder_id}/toggle',
                json={'sync_enabled': False},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()['detail'] == 'Folder not found'
    mock_soft_delete.assert_not_awaited()


def test_update_content_types():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    updated_folder = _make_folder(sync_enabled=True, content_types=['video', 'image'])
    folder_id = updated_folder.id
    folder_repo.update_content_types = AsyncMock(return_value=updated_folder)
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)):
        with TestClient(app) as client:
            response = client.patch(
                f'/api/drive/watched-folders/{folder_id}/content-types',
                json={'content_types': ['video', 'image']},
            )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    payload = WatchedFolderResponse.model_validate(response.json())
    assert payload.id == folder_id
    assert payload.content_types == ['video', 'image']
    folder_repo.update_content_types.assert_awaited_once_with(folder_id, org_ctx.org_id, ['video', 'image'])


def test_update_content_types_invalid():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    db = AsyncMock()
    folder_repo = _FolderRepoMock()
    folder_id = uuid4()
    app = _build_watched_folder_app(db, org_ctx, folder_repo)

    with patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)):
        with TestClient(app) as client:
            empty_response = client.patch(
                f'/api/drive/watched-folders/{folder_id}/content-types',
                json={'content_types': []},
            )
            invalid_response = client.patch(
                f'/api/drive/watched-folders/{folder_id}/content-types',
                json={'content_types': ['audio']},
            )

    app.dependency_overrides.clear()
    assert empty_response.status_code == 422
    assert invalid_response.status_code == 422
    folder_repo.update_content_types.assert_not_awaited()
