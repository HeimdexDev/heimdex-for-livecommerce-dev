from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.agent_intents.models import AgentIntent
from app.modules.agent_intents.repository import (
    AgentIntentRepository,
    generate_intent_code,
)


@pytest.fixture(autouse=True)
def _set_agent_intents_schema_ready():
    from app.modules.agent_intents.schema_check import _reset_cache

    _reset_cache(ready=True)
    yield
    _reset_cache(ready=True)


def _make_intent(
    *,
    org_id=None,
    type="folder_add",
    intent_code="abcdefghijklmnopqrstuvwx",
    payload=None,
    used=False,
    device_id=None,
    created_by=None,
    expires_at=None,
):
    intent = MagicMock(spec=AgentIntent)
    intent.id = uuid4()
    intent.org_id = org_id or uuid4()
    intent.type = type
    intent.intent_code = intent_code
    intent.payload = payload or {}
    intent.used = used
    intent.used_by_device_id = None
    intent.used_at = None
    intent.device_id = device_id or uuid4()
    intent.created_by = created_by or uuid4()
    intent.expires_at = expires_at or (datetime.now(UTC) + timedelta(minutes=10))
    intent.created_at = datetime.now(UTC)
    intent.updated_at = datetime.now(UTC)
    return intent


def _make_device(*, org_id=None, is_revoked=False):
    device = MagicMock()
    device.id = uuid4()
    device.org_id = org_id or uuid4()
    device.device_public_id = "device-abc123"
    device.device_name = "test-cam"
    device.device_secret_hash = ""
    device.is_revoked = is_revoked
    device.last_seen_at = None
    device.created_at = datetime.now(UTC)
    device.updated_at = datetime.now(UTC)
    return device


class TestIntentCodeGeneration:
    def test_code_is_24_chars(self):
        code = generate_intent_code()
        assert len(code) == 24

    def test_code_is_url_safe(self):
        code = generate_intent_code()
        for ch in code:
            assert ch.isalnum() or ch in "-_"


class TestCreateIntent:
    @pytest.mark.asyncio
    async def test_create_intent_success(self):
        from app.modules.agent_intents.router import create_intent
        from app.modules.agent_intents.schemas import CreateIntentRequest
        from app.modules.tenancy.context import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        db = AsyncMock()
        device = _make_device(org_id=org_id)
        user = MagicMock()
        user.id = uuid4()

        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = device
        db.execute = AsyncMock(return_value=db_result)

        intent = _make_intent(org_id=org_id, device_id=device.id, created_by=user.id)

        body = CreateIntentRequest(type="folder_add", device_id=device.id)

        settings = MagicMock()
        settings.agent_intents_enabled = True
        settings.agent_intent_ttl_minutes = 10

        repo = AsyncMock(spec=AgentIntentRepository)
        repo.create.return_value = intent
        repo.build_deep_link_url.return_value = f"heimdex://add-folder?code={intent.intent_code}"

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            result = await create_intent(
                body=body,
                org_ctx=org_ctx,
                db=db,
                repo=repo,
                _admin=user,
                current_user=user,
            )

        assert result.intent_code == intent.intent_code
        assert result.type == intent.type
        assert result.deep_link_url == f"heimdex://add-folder?code={intent.intent_code}"
        repo.create.assert_called_once_with(
            org_id=org_id,
            type="folder_add",
            created_by=user.id,
            device_id=device.id,
            ttl_minutes=10,
        )

    @pytest.mark.asyncio
    async def test_create_intent_feature_disabled_returns_404(self):
        from app.modules.agent_intents.router import create_intent
        from app.modules.agent_intents.schemas import CreateIntentRequest
        from app.modules.tenancy.context import OrgContext

        org_ctx = OrgContext(org_id=uuid4(), org_slug="test-org")
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid4()
        body = CreateIntentRequest(type="folder_add", device_id=uuid4())

        settings = MagicMock()
        settings.agent_intents_enabled = False

        repo = AsyncMock(spec=AgentIntentRepository)

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await create_intent(
                    body=body,
                    org_ctx=org_ctx,
                    db=db,
                    repo=repo,
                    _admin=user,
                    current_user=user,
                )
        assert exc_info.value.status_code == 404


class TestExchangeIntent:
    async def _call_exchange(
        self,
        *,
        intent=None,
        org_id=None,
        device_id=None,
    ):
        from app.modules.agent_intents.router import exchange_intent
        from app.modules.agent_intents.schemas import ExchangeIntentRequest
        from app.modules.tenancy.context import OrgContext

        org_id = org_id or uuid4()
        device_id = device_id or uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        device = _make_device(org_id=org_id)
        device.id = device_id

        body = ExchangeIntentRequest(intent_code="abcdefghijklmnopqrstuvwx")

        settings = MagicMock()
        settings.agent_intents_enabled = True

        repo = AsyncMock(spec=AgentIntentRepository)
        repo.get_by_code_for_update.return_value = intent
        repo.mark_used.return_value = None

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            result = await exchange_intent(
                body=body,
                verified=(org_ctx, device),
                repo=repo,
            )
            return result, repo.mark_used, device

    @pytest.mark.asyncio
    async def test_exchange_success(self):
        org_id = uuid4()
        device_id = uuid4()
        intent = _make_intent(org_id=org_id, device_id=device_id, payload={"path": "/a"})
        result, mock_mark_used, device = await self._call_exchange(
            intent=intent,
            org_id=org_id,
            device_id=device_id,
        )
        assert result.type == "folder_add"
        assert result.org_id == org_id
        assert result.payload == {"path": "/a"}
        mock_mark_used.assert_called_once_with(intent, device.id)

    @pytest.mark.asyncio
    async def test_exchange_expired_returns_410(self):
        org_id = uuid4()
        device_id = uuid4()
        intent = _make_intent(
            org_id=org_id,
            device_id=device_id,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        with pytest.raises(HTTPException) as exc_info:
            await self._call_exchange(intent=intent, org_id=org_id, device_id=device_id)
        assert exc_info.value.status_code == 410

    @pytest.mark.asyncio
    async def test_exchange_used_returns_409(self):
        org_id = uuid4()
        device_id = uuid4()
        intent = _make_intent(org_id=org_id, device_id=device_id, used=True)
        with pytest.raises(HTTPException) as exc_info:
            await self._call_exchange(intent=intent, org_id=org_id, device_id=device_id)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_exchange_wrong_org_returns_403(self):
        device_org_id = uuid4()
        intent = _make_intent(org_id=uuid4(), device_id=uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await self._call_exchange(
                intent=intent,
                org_id=device_org_id,
                device_id=intent.device_id,
            )
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_exchange_wrong_device_returns_403(self):
        org_id = uuid4()
        intent = _make_intent(org_id=org_id, device_id=uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await self._call_exchange(intent=intent, org_id=org_id, device_id=uuid4())
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_exchange_not_found_returns_404(self):
        with pytest.raises(HTTPException) as exc_info:
            await self._call_exchange(intent=None)
        assert exc_info.value.status_code == 404


class TestIntentRateLimit:
    def setup_method(self):
        from app.modules.agent_intents.rate_limit import reset_create, reset_exchange

        reset_create()
        reset_exchange()

    def test_allows_requests_under_limit(self):
        from app.modules.agent_intents.rate_limit import check_create_rate_limit

        for _ in range(10):
            check_create_rate_limit("org-1")

    def test_blocks_over_limit(self):
        from app.modules.agent_intents.rate_limit import check_exchange_rate_limit

        for _ in range(5):
            check_exchange_rate_limit("device-1")
        with pytest.raises(HTTPException) as exc_info:
            check_exchange_rate_limit("device-1")
        assert exc_info.value.status_code == 429

    def test_different_keys_independent(self):
        from app.modules.agent_intents.rate_limit import check_create_rate_limit

        for _ in range(10):
            check_create_rate_limit("org-2")
        check_create_rate_limit("org-3")

    def test_window_reset(self):
        import time as _time
        from unittest.mock import patch as _patch

        from app.modules.agent_intents import rate_limit

        for _ in range(10):
            rate_limit.check_create_rate_limit("org-4")

        original_monotonic = _time.monotonic
        with _patch.object(_time, "monotonic", return_value=original_monotonic() + 601):
            rate_limit.check_create_rate_limit("org-4")


class TestListIntents:
    @pytest.mark.asyncio
    async def test_list_intents_returns_org_intents(self):
        from app.modules.agent_intents.router import list_intents
        from app.modules.tenancy.context import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        user = MagicMock()

        intents = [_make_intent(org_id=org_id), _make_intent(org_id=org_id)]

        settings = MagicMock()
        settings.agent_intents_enabled = True

        repo = AsyncMock(spec=AgentIntentRepository)
        repo.list_by_org.return_value = intents

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            result = await list_intents(org_ctx=org_ctx, repo=repo, _admin=user)

        assert len(result.intents) == 2
        repo.list_by_org.assert_called_once_with(org_id)


class TestSchemaGuard:
    def setup_method(self):
        from app.modules.agent_intents.schema_check import _reset_cache

        _reset_cache(ready=True)

    def teardown_method(self):
        from app.modules.agent_intents.schema_check import _reset_cache

        _reset_cache(ready=True)

    @pytest.mark.asyncio
    async def test_create_intent_returns_503_when_schema_missing(self):
        from app.modules.agent_intents.router import create_intent
        from app.modules.agent_intents.schema_check import _reset_cache
        from app.modules.agent_intents.schemas import CreateIntentRequest
        from app.modules.tenancy.context import OrgContext

        _reset_cache(ready=False)

        org_ctx = OrgContext(org_id=uuid4(), org_slug="test-org")
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid4()
        body = CreateIntentRequest(type="folder_add", device_id=uuid4())

        settings = MagicMock()
        settings.agent_intents_enabled = True

        repo = AsyncMock(spec=AgentIntentRepository)

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await create_intent(
                    body=body,
                    org_ctx=org_ctx,
                    db=db,
                    repo=repo,
                    _admin=user,
                    current_user=user,
                )
        assert exc_info.value.status_code == 503
        assert "migration" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_list_intents_returns_503_when_schema_missing(self):
        from app.modules.agent_intents.router import list_intents
        from app.modules.agent_intents.schema_check import _reset_cache
        from app.modules.tenancy.context import OrgContext

        _reset_cache(ready=False)

        org_ctx = OrgContext(org_id=uuid4(), org_slug="test-org")
        user = MagicMock()

        settings = MagicMock()
        settings.agent_intents_enabled = True

        repo = AsyncMock(spec=AgentIntentRepository)

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await list_intents(org_ctx=org_ctx, repo=repo, _admin=user)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_feature_disabled_returns_404_not_503(self):
        from app.modules.agent_intents.router import create_intent
        from app.modules.agent_intents.schema_check import _reset_cache
        from app.modules.agent_intents.schemas import CreateIntentRequest
        from app.modules.tenancy.context import OrgContext

        _reset_cache(ready=False)

        org_ctx = OrgContext(org_id=uuid4(), org_slug="test-org")
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid4()
        body = CreateIntentRequest(type="folder_add", device_id=uuid4())

        settings = MagicMock()
        settings.agent_intents_enabled = False

        repo = AsyncMock(spec=AgentIntentRepository)

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await create_intent(
                    body=body,
                    org_ctx=org_ctx,
                    db=db,
                    repo=repo,
                    _admin=user,
                    current_user=user,
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_503_message_contains_migration_command(self):
        from app.modules.agent_intents.router import create_intent
        from app.modules.agent_intents.schema_check import _reset_cache
        from app.modules.agent_intents.schemas import CreateIntentRequest
        from app.modules.tenancy.context import OrgContext

        _reset_cache(ready=False)

        org_ctx = OrgContext(org_id=uuid4(), org_slug="test-org")
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid4()
        body = CreateIntentRequest(type="folder_add", device_id=uuid4())

        settings = MagicMock()
        settings.agent_intents_enabled = True

        repo = AsyncMock(spec=AgentIntentRepository)

        with patch("app.modules.agent_intents.router.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await create_intent(
                    body=body,
                    org_ctx=org_ctx,
                    db=db,
                    repo=repo,
                    _admin=user,
                    current_user=user,
                )
        assert "alembic upgrade head" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_schema_check_function(self):
        from app.modules.agent_intents.schema_check import check_agent_intents_table

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = "agent_intents"
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_connect_cm = AsyncMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = mock_connect_cm

        result = await check_agent_intents_table(mock_engine)
        assert result is True

    @pytest.mark.asyncio
    async def test_schema_check_returns_false_when_table_missing(self):
        from app.modules.agent_intents.schema_check import check_agent_intents_table

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_connect_cm = AsyncMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = mock_connect_cm

        result = await check_agent_intents_table(mock_engine)
        assert result is False
