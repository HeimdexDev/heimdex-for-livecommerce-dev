import pytest
from uuid import uuid4

from app.modules.drive.schemas import (
    DriveConnectionCreate,
    DriveConnectionResponse,
    DriveConnectionUpdate,
    DriveFileResponse,
    DriveSecretCreate,
)


class TestDriveConnectionCreate:
    def test_valid_creation(self):
        body = DriveConnectionCreate(
            library_id=uuid4(),
            drive_id="0AMX5qpoGaJvLUk9PVA",
            drive_name="Heimdex Shared Drive",
        )
        assert body.drive_id == "0AMX5qpoGaJvLUk9PVA"

    def test_empty_drive_id_rejected(self):
        with pytest.raises(Exception):
            DriveConnectionCreate(
                library_id=uuid4(),
                drive_id="",
                drive_name="Test",
            )

    def test_empty_drive_name_rejected(self):
        with pytest.raises(Exception):
            DriveConnectionCreate(
                library_id=uuid4(),
                drive_id="abc",
                drive_name="",
            )


class TestDriveConnectionUpdate:
    def test_partial_update_status(self):
        body = DriveConnectionUpdate(status="paused")
        data = body.model_dump(exclude_unset=True)
        assert data == {"status": "paused"}
        assert "drive_name" not in data

    def test_partial_update_name(self):
        body = DriveConnectionUpdate(drive_name="New Name")
        data = body.model_dump(exclude_unset=True)
        assert data == {"drive_name": "New Name"}
        assert "status" not in data

    def test_invalid_status_rejected(self):
        with pytest.raises(Exception):
            DriveConnectionUpdate(status="invalid_status")

    def test_valid_statuses(self):
        for s in ("active", "paused", "disconnected"):
            body = DriveConnectionUpdate(status=s)
            assert body.status == s


class TestDriveSecretCreate:
    def test_valid_creation(self):
        body = DriveSecretCreate(
            sa_key_json='{"type":"service_account"}',
            impersonate_email="admin@example.com",
        )
        assert body.impersonate_email == "admin@example.com"

    def test_empty_sa_key_rejected(self):
        with pytest.raises(Exception):
            DriveSecretCreate(sa_key_json="", impersonate_email="admin@example.com")

    def test_empty_email_rejected(self):
        with pytest.raises(Exception):
            DriveSecretCreate(sa_key_json='{"type":"service_account"}', impersonate_email="")


class TestDriveFileResponse:
    def test_from_attributes(self):
        assert DriveFileResponse.model_config.get("from_attributes") is True

    def test_connection_response_from_attributes(self):
        assert DriveConnectionResponse.model_config.get("from_attributes") is True
