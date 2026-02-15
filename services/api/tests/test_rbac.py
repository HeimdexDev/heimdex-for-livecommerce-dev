from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.auth.dependencies import require_role
from app.modules.users.models import UserRole


class TestRequireRole:
    def _make_user(self, role: UserRole):
        user = MagicMock()
        user.role = role.value
        user.id = uuid4()
        user.email = "test@test.com"
        return user

    @pytest.mark.asyncio
    async def test_admin_allowed(self):
        user = self._make_user(UserRole.ADMIN)
        dep = require_role(UserRole.ADMIN)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_member_rejected_from_admin_route(self):
        user = self._make_user(UserRole.MEMBER)
        dep = require_role(UserRole.ADMIN)
        with pytest.raises(HTTPException) as exc_info:
            await dep(user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_member_allowed_when_member_accepted(self):
        user = self._make_user(UserRole.MEMBER)
        dep = require_role(UserRole.MEMBER, UserRole.ADMIN)
        result = await dep(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_admin_allowed_when_multiple_roles(self):
        user = self._make_user(UserRole.ADMIN)
        dep = require_role(UserRole.MEMBER, UserRole.ADMIN)
        result = await dep(user=user)
        assert result is user
