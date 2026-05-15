from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.tenancy.context import OrgContext


class TestDevRefresh:
    @pytest.mark.asyncio
    async def test_blocked_in_production(self):
        from app.modules.auth.router import dev_refresh

        settings = MagicMock()
        settings.environment = "production"
        settings.enable_dev_refresh = True

        org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
        user = MagicMock()
        user.id = uuid4()
        user.email = "test@test.com"
        user.role = "member"

        with patch("app.modules.auth.router.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await dev_refresh(org_ctx=org_ctx, user=user)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_blocked_when_disabled(self):
        from app.modules.auth.router import dev_refresh

        settings = MagicMock()
        settings.environment = "development"
        settings.enable_dev_refresh = False

        org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
        user = MagicMock()
        user.id = uuid4()
        user.email = "test@test.com"
        user.role = "member"

        with patch("app.modules.auth.router.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await dev_refresh(org_ctx=org_ctx, user=user)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_success_in_development(self):
        from app.modules.auth.router import dev_refresh

        settings = MagicMock()
        settings.environment = "development"
        settings.enable_dev_refresh = True
        settings.jwt_secret_key = "test-secret"
        settings.jwt_algorithm = "HS256"
        settings.jwt_expiration_hours = 24

        org_ctx = OrgContext(org_id=uuid4(), org_slug="testorg")
        user = MagicMock()
        user.id = uuid4()
        user.email = "test@test.com"
        user.role = "member"

        with patch("app.modules.auth.router.get_settings", return_value=settings):
            result = await dev_refresh(org_ctx=org_ctx, user=user)
            assert result.access_token
            assert result.org_slug == "testorg"
