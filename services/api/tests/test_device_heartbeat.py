from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.base import get_db_session
from app.modules.devices.repository import DeviceRepository
from app.modules.devices.router import router as devices_router
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org


def _make_org(*, agent_api_key: str | None) -> MagicMock:
    org = MagicMock()
    org.agent_api_key = agent_api_key
    return org


def _make_device(*, is_revoked: bool = False) -> MagicMock:
    device = MagicMock()
    device.id = uuid4()
    device.org_id = uuid4()
    device.device_public_id = "device-abc123"
    device.is_revoked = is_revoked
    return device


@pytest.fixture
def heartbeat_app() -> FastAPI:
    app = FastAPI()
    app.include_router(devices_router, prefix="/api")
    return app


def _override_dependencies(app: FastAPI, db: AsyncMock, org_ctx: OrgContext) -> None:
    async def _mock_get_db_session():
        return db

    async def _mock_get_current_org() -> OrgContext:
        return org_ctx

    app.dependency_overrides[get_db_session] = _mock_get_db_session
    app.dependency_overrides[get_current_org] = _mock_get_current_org


def test_heartbeat_valid_org_key_updates_last_seen(heartbeat_app: FastAPI):
    org_ctx = OrgContext(org_id=uuid4(), org_slug="org-slug")
    db = AsyncMock()

    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = _make_org(agent_api_key="org-key")
    db.execute.return_value = db_result

    _override_dependencies(heartbeat_app, db, org_ctx)

    settings = MagicMock()
    settings.agent_ingest_enabled = True
    settings.agent_api_key = "global-key"
    settings.device_secret_pepper = "test-pepper"

    device = _make_device(is_revoked=False)
    device.device_secret_hash = "not-matching"

    with (
        patch("app.modules.devices.router.get_settings", return_value=settings),
        patch("app.modules.devices.router.verify_device_secret", return_value=False),
        patch.object(
            DeviceRepository,
            "get_by_org_and_public_id",
            AsyncMock(return_value=device),
        ) as mock_get_device,
        patch.object(
            DeviceRepository,
            "update_last_seen",
            AsyncMock(return_value=None),
        ) as mock_update_last_seen,
    ):
        with TestClient(heartbeat_app) as client:
            response = client.post(
                "/api/devices/heartbeat",
                headers={
                    "host": "devorg.app.heimdex.local",
                    "authorization": "Bearer org-key",
                    "X-Heimdex-Device-Id": "device-abc123",
                },
            )

    heartbeat_app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_get_device.assert_awaited_once_with(org_ctx.org_id, "device-abc123")
    mock_update_last_seen.assert_awaited_once_with(device)


def test_heartbeat_invalid_key_returns_401(heartbeat_app: FastAPI):
    org_ctx = OrgContext(org_id=uuid4(), org_slug="org-slug")
    db = AsyncMock()

    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = _make_org(agent_api_key="org-key")
    db.execute.return_value = db_result

    _override_dependencies(heartbeat_app, db, org_ctx)

    settings = MagicMock()
    settings.agent_ingest_enabled = True
    settings.agent_api_key = "global-key"
    settings.device_secret_pepper = "test-pepper"

    device = _make_device(is_revoked=False)
    device.device_secret_hash = "not-matching"

    with (
        patch("app.modules.devices.router.get_settings", return_value=settings),
        patch("app.modules.devices.router.verify_device_secret", return_value=False),
        patch.object(
            DeviceRepository,
            "get_by_org_and_public_id",
            AsyncMock(return_value=device),
        ),
    ):
        with TestClient(heartbeat_app) as client:
            response = client.post(
                "/api/devices/heartbeat",
                headers={
                    "host": "devorg.app.heimdex.local",
                    "authorization": "Bearer wrong-key",
                    "X-Heimdex-Device-Id": "device-abc123",
                },
            )

    heartbeat_app.dependency_overrides.clear()
    assert response.status_code == 401


def test_heartbeat_missing_device_id_returns_422(heartbeat_app: FastAPI):
    org_ctx = OrgContext(org_id=uuid4(), org_slug="org-slug")
    db = AsyncMock()

    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = _make_org(agent_api_key="org-key")
    db.execute.return_value = db_result

    _override_dependencies(heartbeat_app, db, org_ctx)

    settings = MagicMock()
    settings.agent_ingest_enabled = True
    settings.agent_api_key = "global-key"

    with patch("app.modules.devices.router.get_settings", return_value=settings):
        with TestClient(heartbeat_app) as client:
            response = client.post(
                "/api/devices/heartbeat",
                headers={
                    "host": "devorg.app.heimdex.local",
                    "authorization": "Bearer org-key",
                },
            )

    heartbeat_app.dependency_overrides.clear()
    assert response.status_code == 422


def test_heartbeat_revoked_device_returns_401(heartbeat_app: FastAPI):
    org_ctx = OrgContext(org_id=uuid4(), org_slug="org-slug")
    db = AsyncMock()

    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = _make_org(agent_api_key="org-key")
    db.execute.return_value = db_result

    _override_dependencies(heartbeat_app, db, org_ctx)

    settings = MagicMock()
    settings.agent_ingest_enabled = True
    settings.agent_api_key = "global-key"

    device = _make_device(is_revoked=True)

    with (
        patch("app.modules.devices.router.get_settings", return_value=settings),
        patch.object(
            DeviceRepository,
            "get_by_org_and_public_id",
            AsyncMock(return_value=device),
        ),
    ):
        with TestClient(heartbeat_app) as client:
            response = client.post(
                "/api/devices/heartbeat",
                headers={
                    "host": "devorg.app.heimdex.local",
                    "authorization": "Bearer org-key",
                    "X-Heimdex-Device-Id": "device-abc123",
                },
            )

    heartbeat_app.dependency_overrides.clear()
    assert response.status_code == 401


def test_heartbeat_unknown_device_returns_404(heartbeat_app: FastAPI):
    org_ctx = OrgContext(org_id=uuid4(), org_slug="org-slug")
    db = AsyncMock()

    db_result = MagicMock()
    db_result.scalar_one_or_none.return_value = _make_org(agent_api_key="org-key")
    db.execute.return_value = db_result

    _override_dependencies(heartbeat_app, db, org_ctx)

    settings = MagicMock()
    settings.agent_ingest_enabled = True
    settings.agent_api_key = "global-key"

    with (
        patch("app.modules.devices.router.get_settings", return_value=settings),
        patch.object(
            DeviceRepository,
            "get_by_org_and_public_id",
            AsyncMock(return_value=None),
        ),
    ):
        with TestClient(heartbeat_app) as client:
            response = client.post(
                "/api/devices/heartbeat",
                headers={
                    "host": "devorg.app.heimdex.local",
                    "authorization": "Bearer org-key",
                    "X-Heimdex-Device-Id": "device-abc123",
                },
            )

    heartbeat_app.dependency_overrides.clear()
    assert response.status_code == 404
