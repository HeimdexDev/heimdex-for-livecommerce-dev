from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.modules.devices.repository import (
    DeviceRepository,
    generate_device_secret,
    hash_device_secret,
    verify_device_secret,
)
from app.modules.ingest.auth import verify_agent_token
from app.modules.tenancy.context import OrgContext

PEPPER = "test-pepper"


def _make_device(
    *,
    org_id=None,
    device_public_id="device-abc123",
    device_name="test-cam-01",
    device_secret_hash="",
    is_revoked=False,
    last_seen_at=None,
):
    device = MagicMock()
    device.id = uuid4()
    device.org_id = org_id or uuid4()
    device.device_public_id = device_public_id
    device.device_name = device_name
    device.device_secret_hash = device_secret_hash
    device.is_revoked = is_revoked
    device.last_seen_at = last_seen_at
    device.created_at = datetime.now(UTC)
    device.updated_at = datetime.now(UTC)
    return device


def _make_org(*, agent_api_key=None):
    org = MagicMock()
    org.agent_api_key = agent_api_key
    return org


class TestDeviceSecretHashing:
    def test_hash_deterministic(self):
        secret = "my-secret"
        h1 = hash_device_secret(secret, PEPPER)
        h2 = hash_device_secret(secret, PEPPER)
        assert h1 == h2

    def test_hash_different_pepper(self):
        secret = "my-secret"
        h1 = hash_device_secret(secret, "pepper-a")
        h2 = hash_device_secret(secret, "pepper-b")
        assert h1 != h2

    def test_hash_different_secret(self):
        h1 = hash_device_secret("secret-a", PEPPER)
        h2 = hash_device_secret("secret-b", PEPPER)
        assert h1 != h2

    def test_verify_correct(self):
        secret = "my-secret"
        h = hash_device_secret(secret, PEPPER)
        assert verify_device_secret(secret, h, PEPPER) is True

    def test_verify_wrong_secret(self):
        h = hash_device_secret("correct", PEPPER)
        assert verify_device_secret("wrong", h, PEPPER) is False

    def test_verify_wrong_pepper(self):
        secret = "my-secret"
        h = hash_device_secret(secret, PEPPER)
        assert verify_device_secret(secret, h, "wrong-pepper") is False

    def test_generate_secret_length(self):
        secret = generate_device_secret()
        assert len(secret) >= 32

    def test_generate_secret_unique(self):
        s1 = generate_device_secret()
        s2 = generate_device_secret()
        assert s1 != s2

    def test_hash_output_is_hex(self):
        h = hash_device_secret("secret", PEPPER)
        int(h, 16)
        assert len(h) == 64


class TestPerDeviceIngestAuth:
    async def _run_verify(
        self,
        *,
        token: str,
        mode: str,
        device_public_id: str | None = "device-abc123",
        device: MagicMock | None = None,
        ingest_enabled: bool = True,
        org_key: str | None = None,
        global_key: str = "global-key",
    ) -> OrgContext:
        org_ctx = OrgContext(org_id=uuid4(), org_slug="org-slug")
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = _make_org(agent_api_key=org_key)
        db.execute.return_value = db_result

        settings = MagicMock()
        settings.agent_ingest_enabled = ingest_enabled
        settings.agent_api_key = global_key
        settings.agent_api_key_mode = mode
        settings.device_secret_pepper = PEPPER

        device_repo = AsyncMock(spec=DeviceRepository)
        device_repo.get_by_org_and_public_id.return_value = device
        device_repo.update_last_seen.return_value = None

        with patch("app.modules.ingest.auth.get_settings", return_value=settings):
            return await verify_agent_token(
                credentials=credentials,
                org_ctx=org_ctx,
                db=db,
                device_repo=device_repo,
                x_heimdex_device_id=device_public_id,
            )

    @pytest.mark.asyncio
    async def test_per_device_valid_secret(self):
        raw_secret = "device-secret-abc"
        secret_hash = hash_device_secret(raw_secret, PEPPER)
        device = _make_device(device_secret_hash=secret_hash)

        result = await self._run_verify(
            token=raw_secret,
            mode="per-device",
            device=device,
        )
        assert isinstance(result, OrgContext)

    @pytest.mark.asyncio
    async def test_per_device_wrong_secret(self):
        secret_hash = hash_device_secret("correct-secret", PEPPER)
        device = _make_device(device_secret_hash=secret_hash)

        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token="wrong-secret",
                mode="per-device",
                device=device,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_per_device_missing_device_id_header(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token="any-token",
                mode="per-device",
                device_public_id=None,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_per_device_device_not_found(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token="any-token",
                mode="per-device",
                device=None,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_per_device_device_revoked(self):
        raw_secret = "device-secret-abc"
        secret_hash = hash_device_secret(raw_secret, PEPPER)
        device = _make_device(device_secret_hash=secret_hash, is_revoked=True)

        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token=raw_secret,
                mode="per-device",
                device=device,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_per_device_org_key_rejected(self):
        """In per-device mode, org API keys must NOT be accepted for ingest."""
        device = _make_device(device_secret_hash="irrelevant")

        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token="org-key",
                mode="per-device",
                device=device,
                org_key="org-key",
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_per_device_ingest_disabled(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._run_verify(
                token="any-token",
                mode="per-device",
                ingest_enabled=False,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_global_mode_still_works(self):
        result = await self._run_verify(
            token="global-key",
            mode="global",
            org_key=None,
            global_key="global-key",
        )
        assert isinstance(result, OrgContext)

    @pytest.mark.asyncio
    async def test_per_org_mode_still_works(self):
        result = await self._run_verify(
            token="org-key",
            mode="per-org",
            org_key="org-key",
        )
        assert isinstance(result, OrgContext)


class TestDeviceRepositoryLastSeen:
    @pytest.mark.asyncio
    async def test_update_last_seen_when_stale(self):
        session = AsyncMock()
        repo = DeviceRepository(session)

        stale_time = datetime.now(UTC) - timedelta(minutes=10)
        device = _make_device(last_seen_at=stale_time)

        await repo.update_last_seen(device)
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_skip_update_when_recent(self):
        session = AsyncMock()
        repo = DeviceRepository(session)

        recent_time = datetime.now(UTC) - timedelta(minutes=1)
        device = _make_device(last_seen_at=recent_time)

        await repo.update_last_seen(device)
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_when_never_seen(self):
        session = AsyncMock()
        repo = DeviceRepository(session)

        device = _make_device(last_seen_at=None)

        await repo.update_last_seen(device)
        session.execute.assert_called_once()
