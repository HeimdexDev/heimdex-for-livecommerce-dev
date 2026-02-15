from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.devices.pairing import PairingCode, PairingCodeRepository, generate_pairing_code

PEPPER = "test-pepper"


def _make_pairing_code(
    *,
    org_id=None,
    code="482917",
    expires_at=None,
    used=False,
    used_by_device_id=None,
):
    pc = MagicMock(spec=PairingCode)
    pc.id = uuid4()
    pc.org_id = org_id or uuid4()
    pc.code = code
    pc.expires_at = expires_at or (datetime.now(UTC) + timedelta(minutes=10))
    pc.used = used
    pc.used_by_device_id = used_by_device_id
    pc.created_at = datetime.now(UTC)
    pc.updated_at = datetime.now(UTC)
    return pc


def _make_device(*, device_public_id="device-abc123", is_revoked=False):
    device = MagicMock()
    device.id = uuid4()
    device.org_id = uuid4()
    device.device_public_id = device_public_id
    device.device_name = "test-cam"
    device.device_secret_hash = ""
    device.is_revoked = is_revoked
    device.last_seen_at = None
    device.created_at = datetime.now(UTC)
    device.updated_at = datetime.now(UTC)
    return device


class TestPairingCodeGeneration:
    def test_code_is_six_digits(self):
        code = generate_pairing_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_code_can_have_leading_zeros(self):
        codes = {generate_pairing_code() for _ in range(1000)}
        assert len(codes) > 1

    def test_code_range(self):
        for _ in range(100):
            code = generate_pairing_code()
            val = int(code)
            assert 0 <= val <= 999999


class TestPairingCodeExchange:
    """Tests for POST /api/devices/pair endpoint logic."""

    async def _call_pair(
        self,
        *,
        code="482917",
        pairing=None,
        existing_device=None,
        device_public_id="new-device-01",
        device_name="Test Camera",
    ):
        from app.modules.devices.router import pair_device
        from app.modules.devices.schemas import PairingCodeExchangeRequest
        from app.modules.tenancy.context import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")

        db = AsyncMock()

        request = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        body = PairingCodeExchangeRequest(
            code=code,
            device_public_id=device_public_id,
            device_name=device_name,
        )

        created_device = _make_device(device_public_id=device_public_id)

        settings = MagicMock()
        settings.device_secret_pepper = PEPPER
        settings.pairing_code_ttl_minutes = 10

        with (
            patch("app.modules.devices.router.get_settings", return_value=settings),
            patch.object(
                PairingCodeRepository,
                "get_by_org_and_code_for_update",
                return_value=pairing,
            ),
            patch.object(
                PairingCodeRepository,
                "mark_used",
                return_value=None,
            ) as mock_mark_used,
            patch(
                "app.modules.devices.router.DeviceRepository"
            ) as mock_device_repo_cls,
        ):
            repo_instance = mock_device_repo_cls.return_value
            repo_instance.get_by_org_and_public_id = AsyncMock(
                return_value=existing_device,
            )
            repo_instance.create = AsyncMock(return_value=created_device)

            result = await pair_device(
                body=body,
                request=request,
                org_ctx=org_ctx,
                db=db,
            )
            return result, mock_mark_used

    @pytest.mark.asyncio
    async def test_pair_valid_code(self):
        pairing = _make_pairing_code()
        result, mock_mark_used = await self._call_pair(pairing=pairing)
        assert result.device_secret is not None
        assert len(result.device_secret) >= 32
        mock_mark_used.assert_called_once()

    @pytest.mark.asyncio
    async def test_pair_invalid_code_returns_401(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._call_pair(pairing=None)
        assert exc_info.value.status_code == 401
        assert "Invalid pairing code" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_pair_expired_code_returns_410(self):
        expired = _make_pairing_code(
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        with pytest.raises(HTTPException) as exc_info:
            await self._call_pair(pairing=expired)
        assert exc_info.value.status_code == 410
        assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_pair_used_code_returns_409(self):
        used = _make_pairing_code(used=True, used_by_device_id=uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await self._call_pair(pairing=used)
        assert exc_info.value.status_code == 409
        assert "already been used" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_pair_device_already_registered_returns_409(self):
        pairing = _make_pairing_code()
        existing = _make_device()
        with pytest.raises(HTTPException) as exc_info:
            await self._call_pair(pairing=pairing, existing_device=existing)
        assert exc_info.value.status_code == 409
        assert "already registered" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_pair_device_revoked_returns_409(self):
        pairing = _make_pairing_code()
        revoked = _make_device(is_revoked=True)
        with pytest.raises(HTTPException) as exc_info:
            await self._call_pair(pairing=pairing, existing_device=revoked)
        assert exc_info.value.status_code == 409
        assert "revoked" in exc_info.value.detail.lower()


class TestPairingCodeCreate:
    """Tests for POST /api/devices/pairing-code endpoint logic."""

    @pytest.mark.asyncio
    async def test_create_pairing_code(self):
        from app.modules.devices.router import create_pairing_code
        from app.modules.tenancy.context import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        db = AsyncMock()

        pairing = _make_pairing_code(org_id=org_id)

        settings = MagicMock()
        settings.pairing_code_ttl_minutes = 10

        with (
            patch("app.modules.devices.router.get_settings", return_value=settings),
            patch.object(
                PairingCodeRepository,
                "create",
                return_value=pairing,
            ) as mock_create,
        ):
            result = await create_pairing_code(
                org_ctx=org_ctx,
                db=db,
            )
            assert len(result.code) == 6
            assert result.expires_at is not None
            mock_create.assert_called_once_with(
                org_id=org_id,
                ttl_minutes=10,
            )


class TestPairingRateLimit:

    def setup_method(self):
        from app.modules.devices.rate_limit import reset
        reset()

    def test_allows_requests_under_limit(self):
        from app.modules.devices.rate_limit import check_pairing_rate_limit
        for _ in range(5):
            check_pairing_rate_limit("10.0.0.1")

    def test_blocks_over_limit_with_429(self):
        from app.modules.devices.rate_limit import check_pairing_rate_limit
        for _ in range(5):
            check_pairing_rate_limit("10.0.0.2")
        with pytest.raises(HTTPException) as exc_info:
            check_pairing_rate_limit("10.0.0.2")
        assert exc_info.value.status_code == 429
        assert "Too many pairing attempts" in exc_info.value.detail

    def test_different_ips_are_independent(self):
        from app.modules.devices.rate_limit import check_pairing_rate_limit
        for _ in range(5):
            check_pairing_rate_limit("10.0.0.3")
        check_pairing_rate_limit("10.0.0.4")

    def test_window_reset_allows_new_attempts(self):
        import time as _time
        from unittest.mock import patch as _patch

        from app.modules.devices import rate_limit

        rate_limit.reset()
        for _ in range(5):
            rate_limit.check_pairing_rate_limit("10.0.0.5")

        original_monotonic = _time.monotonic
        with _patch.object(_time, "monotonic", return_value=original_monotonic() + 601):
            rate_limit.check_pairing_rate_limit("10.0.0.5")
