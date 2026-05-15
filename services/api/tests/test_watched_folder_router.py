import json
import os
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.dependencies import get_db_session, get_scene_opensearch_client, get_watched_folder_repository
from app.modules.auth.service import get_current_user
from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository
from app.modules.drive.watched_folder_router import _get_drive_client_for_org, router as watched_folder_router
from app.modules.drive.watched_folder_schemas import FolderTreeResponse, ToggleFolderResponse, WatchedFolderResponse
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import UserRole


def _mock_admin():
    user = MagicMock()
    user.id = uuid4()
    user.org_id = uuid4()
    user.email = "admin@test.com"
    user.role = UserRole.ADMIN.value
    return user


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
        self.get_descendant_folder_names: AsyncMock = AsyncMock(return_value=[])


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

    app.dependency_overrides[get_current_user] = lambda: _mock_admin()
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

    folder_names = [updated_folder.google_folder_id, 'child-folder-id']
    folder_repo.get_descendant_folder_names = AsyncMock(return_value=folder_names)
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
    mock_soft_delete.assert_awaited_once_with(org_ctx.org_id, updated_folder.connection_id, folder_names)
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


# ---------------------------------------------------------------------------
# Helpers for _get_drive_client_for_org tests
# ---------------------------------------------------------------------------

def _make_encryption_key() -> str:
    """Return a fresh 256-bit AES key as a hex string."""
    return os.urandom(32).hex()


def _encrypt_payload(payload: dict, key_hex: str) -> tuple[bytes, bytes]:
    """AES-256-GCM encrypt *payload* and return (nonce, ciphertext)."""
    key = bytes.fromhex(key_hex)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, json.dumps(payload).encode(), None)
    return nonce, ciphertext


def _make_oauth_secret(key_hex: str) -> SimpleNamespace:
    """Return a minimal fake DriveSecret for an oauth_token credential."""
    payload = {
        "refresh_token": "rt-123",
        "client_id": "cid-456",
        "client_secret": "csec-789",
    }
    nonce, ciphertext = _encrypt_payload(payload, key_hex)
    return SimpleNamespace(
        nonce=nonce,
        encrypted_value=ciphertext,
        impersonate_email="user@example.com",
    )


def _make_sa_secret(key_hex: str) -> SimpleNamespace:
    """Return a minimal fake DriveSecret for a service_account_key credential."""
    payload = {"type": "service_account", "project_id": "proj-1"}
    nonce, ciphertext = _encrypt_payload(payload, key_hex)
    return SimpleNamespace(
        nonce=nonce,
        encrypted_value=ciphertext,
        impersonate_email="sa@example.com",
    )


class TestGetDriveClientForOrg:
    @pytest.mark.asyncio
    async def test_prefers_oauth_when_oauth_token_exists(self):
        key_hex = _make_encryption_key()
        org_id = uuid4()
        oauth_secret = _make_oauth_secret(key_hex)

        secret_repo = MagicMock()
        secret_repo.get_by_org = AsyncMock(return_value=oauth_secret)

        mock_client = MagicMock()
        with patch(
            'app.modules.drive.watched_folder_router.DriveClient.from_oauth_token',
            return_value=mock_client,
        ):
            client, auth_type = await _get_drive_client_for_org(org_id, secret_repo, key_hex)

        assert auth_type == 'oauth'
        assert client is mock_client
        # get_by_org should have been called once for oauth_token only
        secret_repo.get_by_org.assert_awaited_once_with(org_id, secret_type='oauth_token')

    @pytest.mark.asyncio
    async def test_falls_back_to_sa_when_no_oauth_token(self):
        key_hex = _make_encryption_key()
        org_id = uuid4()
        sa_secret = _make_sa_secret(key_hex)

        secret_repo = MagicMock()
        # First call (oauth_token) → None; second call (service_account_key) → secret
        secret_repo.get_by_org = AsyncMock(side_effect=[None, sa_secret])

        mock_client = MagicMock()
        with patch(
            'app.modules.drive.watched_folder_router.DriveClient',
            return_value=mock_client,
        ):
            client, auth_type = await _get_drive_client_for_org(org_id, secret_repo, key_hex)

        assert auth_type == 'sa'
        assert client is mock_client
        assert secret_repo.get_by_org.await_count == 2

    @pytest.mark.asyncio
    async def test_raises_400_when_no_credentials_found(self):
        key_hex = _make_encryption_key()
        org_id = uuid4()

        secret_repo = MagicMock()
        secret_repo.get_by_org = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await _get_drive_client_for_org(org_id, secret_repo, key_hex)

        assert exc_info.value.status_code == 400
        assert secret_repo.get_by_org.await_count == 2

    @pytest.mark.asyncio
    async def test_raises_400_on_expired_oauth_token(self):
        from google.auth.exceptions import RefreshError

        key_hex = _make_encryption_key()
        org_id = uuid4()
        oauth_secret = _make_oauth_secret(key_hex)

        secret_repo = MagicMock()
        secret_repo.get_by_org = AsyncMock(return_value=oauth_secret)

        with patch(
            'app.modules.drive.watched_folder_router.DriveClient.from_oauth_token',
            side_effect=RefreshError('token expired'),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _get_drive_client_for_org(org_id, secret_repo, key_hex)

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# enumerate-folders endpoint: SA auth skips My Drive
# ---------------------------------------------------------------------------

def _build_enumerate_app(
    org_ctx: OrgContext,
    mock_drive_client_for_org,
    conn_repo_mock,
    folder_repo_mock,
) -> FastAPI:
    from app.dependencies import (
        get_drive_connection_repository,
        get_drive_secret_repository,
        get_watched_folder_repository,
    )

    app = FastAPI()
    app.include_router(watched_folder_router, prefix='/api')

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    async def _mock_conn_repo():
        return conn_repo_mock

    async def _mock_secret_repo():
        return MagicMock()

    def _mock_folder_repo():
        return folder_repo_mock

    app.dependency_overrides[get_current_user] = lambda: _mock_admin()
    app.dependency_overrides[get_current_org] = _mock_get_current_org
    app.dependency_overrides[get_drive_connection_repository] = _mock_conn_repo
    app.dependency_overrides[get_drive_secret_repository] = _mock_secret_repo
    app.dependency_overrides[get_watched_folder_repository] = _mock_folder_repo
    return app


@dataclass
class _ConnModel:
    id: UUID
    org_id: UUID
    library_id: UUID
    drive_id: str | None
    drive_name: str | None
    scope_type: str


def _make_conn(*, scope_type: str, org_id: UUID, library_id: UUID, drive_id: str | None = None) -> _ConnModel:
    return _ConnModel(
        id=uuid4(),
        org_id=org_id,
        library_id=library_id,
        drive_id=drive_id,
        drive_name='Shared Drive' if drive_id else 'My Drive',
        scope_type=scope_type,
    )


def test_enumerate_skips_my_drive_for_sa_auth():
    org_ctx = OrgContext(org_id=uuid4(), org_slug='testorg')
    library_id = uuid4()

    shared_conn = _make_conn(
        scope_type='shared_drive',
        org_id=org_ctx.org_id,
        library_id=library_id,
        drive_id='sd-abc',
    )

    mock_drive_client = MagicMock()
    mock_drive_client.list_shared_drives.return_value = [{'id': 'sd-abc', 'name': 'Shared Drive'}]
    mock_drive_client.list_all_folders.return_value = []

    conn_repo_mock = MagicMock()
    conn_repo_mock.list_by_org = AsyncMock(return_value=[shared_conn])
    conn_repo_mock.session = MagicMock()
    conn_repo_mock.session.add = MagicMock()
    conn_repo_mock.session.flush = AsyncMock()

    folder_repo_mock = _FolderRepoMock()
    folder_repo_mock.list_by_org = AsyncMock(return_value=[])
    folder_repo_mock.bulk_upsert = AsyncMock(return_value=None)

    app = _build_enumerate_app(org_ctx, None, conn_repo_mock, folder_repo_mock)

    with (
        patch('app.modules.drive.router.get_settings', return_value=SimpleNamespace(drive_connector_enabled=True)),
        patch(
            'app.modules.drive.watched_folder_router._get_drive_client_for_org',
            new=AsyncMock(return_value=(mock_drive_client, 'sa')),
        ),
    ):
        with TestClient(app) as client:
            response = client.post('/api/drive/watched-folders/enumerate-folders')

    app.dependency_overrides.clear()
    assert response.status_code == 200

    # list_all_folders should have been called once for the shared drive only,
    # never for My Drive (drive_id=None)
    calls = mock_drive_client.list_all_folders.call_args_list
    assert all(call.args[0] is not None for call in calls), (
        "list_all_folders was called with None (My Drive) during SA auth — should be skipped"
    )
    called_drive_ids = [call.args[0] for call in calls]
    assert 'sd-abc' in called_drive_ids
