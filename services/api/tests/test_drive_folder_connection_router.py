from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.drive.router import create_folder_connection
from app.modules.drive.schemas import DriveFolderConnectionCreate
from app.modules.tenancy.context import OrgContext


@pytest.mark.asyncio
async def test_create_folder_connection_populates_drive_id_for_shared_drive_folder():
    org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
    body = DriveFolderConnectionCreate(
        library_id=uuid4(),
        folder_id="folder-123",
        folder_name="Shared Folder",
        folder_path="Shared Folder",
    )

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    secret = MagicMock()
    secret.nonce = b"nonce"
    secret.encrypted_value = b"encrypted"

    secret_repo = MagicMock()
    secret_repo.get_by_org = AsyncMock(return_value=secret)

    drive_service = MagicMock()
    drive_service.files.return_value.get.return_value.execute.return_value = {"driveId": "shared-drive-123"}
    drive_client = MagicMock()
    drive_client._service = drive_service

    settings = SimpleNamespace(
        google_oauth_client_id="google-client-id",
        drive_sa_encryption_key="00" * 32,
    )

    with (
        patch("app.modules.drive.router.get_settings", return_value=settings),
        patch("app.modules.drive.router.DriveSecretRepository", return_value=secret_repo),
        patch("app.modules.drive.models.DriveConnection", side_effect=lambda **kwargs: SimpleNamespace(**kwargs)),
        patch(
            "app.modules.drive.router._decrypt_oauth_token_data",
            return_value={
                "refresh_token": "refresh",
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
        ),
        patch("app.modules.drive.google_client.DriveClient.from_oauth_token", return_value=drive_client),
    ):
        conn = await create_folder_connection(
            body=body,
            org_ctx=org_ctx,
            _admin=MagicMock(role="admin"),
            db=db,
            secret_repo=secret_repo,
            _=None,
        )

    assert conn.drive_id == "shared-drive-123"
    drive_service.files.return_value.get.assert_called_once_with(
        fileId="folder-123",
        fields="driveId",
        supportsAllDrives=True,
    )
