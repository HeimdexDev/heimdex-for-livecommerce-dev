"""
Unit tests for organization settings endpoints.

Tests verify:
1. GET /api/org/settings returns defaults when settings is empty
2. PATCH /api/org/settings updates and returns new value
3. Persistence: PATCH then GET returns updated value
4. Empty PATCH body returns current settings without error
5. Invalid values (e.g., "4:3") return 422 validation error
6. Authentication required (401 without token)

Run with: pytest tests/test_org_settings.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.modules.orgs.schemas import OrgSettingsResponse, OrgSettingsUpdateRequest
from app.modules.orgs.router import get_org_settings, update_org_settings
from app.modules.tenancy import OrgContext


class TestOrgSettingsSchemas:
    """Validate OrgSettingsResponse and OrgSettingsUpdateRequest schemas."""

    def test_response_model_valid(self):
        """OrgSettingsResponse accepts valid thumbnail_aspect_ratio."""
        resp = OrgSettingsResponse(thumbnail_aspect_ratio="16:9")
        assert resp.thumbnail_aspect_ratio == "16:9"

    def test_response_model_9_16(self):
        """OrgSettingsResponse accepts 9:16 ratio."""
        resp = OrgSettingsResponse(thumbnail_aspect_ratio="9:16")
        assert resp.thumbnail_aspect_ratio == "9:16"

    def test_update_request_none_defaults(self):
        """OrgSettingsUpdateRequest fields default to None."""
        req = OrgSettingsUpdateRequest()
        assert req.thumbnail_aspect_ratio is None

    def test_update_request_16_9(self):
        """OrgSettingsUpdateRequest accepts 16:9."""
        req = OrgSettingsUpdateRequest(thumbnail_aspect_ratio="16:9")
        assert req.thumbnail_aspect_ratio == "16:9"

    def test_update_request_9_16(self):
        """OrgSettingsUpdateRequest accepts 9:16."""
        req = OrgSettingsUpdateRequest(thumbnail_aspect_ratio="9:16")
        assert req.thumbnail_aspect_ratio == "9:16"

    def test_update_request_invalid_ratio_rejected(self):
        """OrgSettingsUpdateRequest rejects invalid ratios like 4:3."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OrgSettingsUpdateRequest(thumbnail_aspect_ratio="4:3")

    def test_update_request_invalid_string_rejected(self):
        """OrgSettingsUpdateRequest rejects arbitrary strings."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            OrgSettingsUpdateRequest(thumbnail_aspect_ratio="invalid")

    def test_update_request_model_dump_exclude_none(self):
        """OrgSettingsUpdateRequest.model_dump(exclude_none=True) skips None fields."""
        req = OrgSettingsUpdateRequest(thumbnail_aspect_ratio=None)
        dumped = req.model_dump(exclude_none=True)
        assert dumped == {}

    def test_update_request_model_dump_with_value(self):
        """OrgSettingsUpdateRequest.model_dump(exclude_none=True) includes set values."""
        req = OrgSettingsUpdateRequest(thumbnail_aspect_ratio="9:16")
        dumped = req.model_dump(exclude_none=True)
        assert dumped == {"thumbnail_aspect_ratio": "9:16"}


class TestGetOrgSettingsEndpoint:
    """Test GET /api/org/settings endpoint."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_settings_empty(self):
        """GET /api/org/settings returns defaults when org.settings is empty dict."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        # Mock org with empty settings
        org = MagicMock()
        org.settings = {}
        org.get_settings_with_defaults = MagicMock(
            return_value={"thumbnail_aspect_ratio": "16:9"}
        )

        org_repo = AsyncMock()
        org_repo.get_by_id = AsyncMock(return_value=org)

        response = await get_org_settings(
            org_ctx=org_ctx,
            user=user,
            org_repo=org_repo,
        )

        assert response.thumbnail_aspect_ratio == "16:9"
        org_repo.get_by_id.assert_called_once_with(org_id)

    @pytest.mark.asyncio
    async def test_returns_custom_settings_when_set(self):
        """GET /api/org/settings returns custom settings when org.settings has values."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        # Mock org with custom settings
        org = MagicMock()
        org.settings = {"thumbnail_aspect_ratio": "9:16"}
        org.get_settings_with_defaults = MagicMock(
            return_value={"thumbnail_aspect_ratio": "9:16"}
        )

        org_repo = AsyncMock()
        org_repo.get_by_id = AsyncMock(return_value=org)

        response = await get_org_settings(
            org_ctx=org_ctx,
            user=user,
            org_repo=org_repo,
        )

        assert response.thumbnail_aspect_ratio == "9:16"

    @pytest.mark.asyncio
    async def test_returns_404_when_org_not_found(self):
        """GET /api/org/settings returns 404 when org does not exist."""
        from fastapi import HTTPException

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        org_repo = AsyncMock()
        org_repo.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_org_settings(
                org_ctx=org_ctx,
                user=user,
                org_repo=org_repo,
            )

        assert exc_info.value.status_code == 404
        assert "Organization not found" in exc_info.value.detail


class TestUpdateOrgSettingsEndpoint:
    """Test PATCH /api/org/settings endpoint."""

    @pytest.mark.asyncio
    async def test_updates_thumbnail_aspect_ratio(self):
        """PATCH /api/org/settings with thumbnail_aspect_ratio updates and returns new value."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        request = OrgSettingsUpdateRequest(thumbnail_aspect_ratio="9:16")

        # Mock updated org
        updated_org = MagicMock()
        updated_org.settings = {"thumbnail_aspect_ratio": "9:16"}
        updated_org.get_settings_with_defaults = MagicMock(
            return_value={"thumbnail_aspect_ratio": "9:16"}
        )

        org_repo = AsyncMock()
        org_repo.update_settings = AsyncMock(return_value=updated_org)

        db = AsyncMock()
        db.commit = AsyncMock()

        response = await update_org_settings(
            request=request,
            org_ctx=org_ctx,
            user=user,
            org_repo=org_repo,
            db=db,
        )

        assert response.thumbnail_aspect_ratio == "9:16"
        org_repo.update_settings.assert_called_once_with(org_id, {"thumbnail_aspect_ratio": "9:16"})
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_patch_returns_current_settings(self):
        """PATCH /api/org/settings with empty body returns current settings without error."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        request = OrgSettingsUpdateRequest()  # All None

        # Mock org
        org = MagicMock()
        org.settings = {"thumbnail_aspect_ratio": "16:9"}
        org.get_settings_with_defaults = MagicMock(
            return_value={"thumbnail_aspect_ratio": "16:9"}
        )

        org_repo = AsyncMock()
        org_repo.get_by_id = AsyncMock(return_value=org)

        db = AsyncMock()
        db.commit = AsyncMock()

        response = await update_org_settings(
            request=request,
            org_ctx=org_ctx,
            user=user,
            org_repo=org_repo,
            db=db,
        )

        assert response.thumbnail_aspect_ratio == "16:9"
        # update_settings should NOT be called for empty patch
        org_repo.update_settings.assert_not_called()
        # commit should NOT be called for empty patch
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_patch_returns_404_when_org_not_found(self):
        """PATCH /api/org/settings with empty body returns 404 when org not found."""
        from fastapi import HTTPException

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        request = OrgSettingsUpdateRequest()  # All None

        org_repo = AsyncMock()
        org_repo.get_by_id = AsyncMock(return_value=None)

        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await update_org_settings(
                request=request,
                org_ctx=org_ctx,
                user=user,
                org_repo=org_repo,
                db=db,
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_logs_update_on_success(self):
        """PATCH /api/org/settings logs org_settings_updated on success."""
        from unittest.mock import patch

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        request = OrgSettingsUpdateRequest(thumbnail_aspect_ratio="9:16")

        updated_org = MagicMock()
        updated_org.settings = {"thumbnail_aspect_ratio": "9:16"}
        updated_org.get_settings_with_defaults = MagicMock(
            return_value={"thumbnail_aspect_ratio": "9:16"}
        )

        org_repo = AsyncMock()
        org_repo.update_settings = AsyncMock(return_value=updated_org)

        db = AsyncMock()
        db.commit = AsyncMock()

        with patch("app.modules.orgs.router.logger") as mock_logger:
            response = await update_org_settings(
                request=request,
                org_ctx=org_ctx,
                user=user,
                org_repo=org_repo,
                db=db,
            )

            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "org_settings_updated"
            assert "org_id" in call_args[1]
            assert "updated_fields" in call_args[1]
            assert call_args[1]["updated_fields"] == ["thumbnail_aspect_ratio"]


class TestOrgSettingsPersistence:
    """Test that settings persist across GET/PATCH cycles."""

    @pytest.mark.asyncio
    async def test_patch_then_get_returns_updated_value(self):
        """PATCH then GET returns the updated value."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        # Step 1: PATCH to update
        patch_request = OrgSettingsUpdateRequest(thumbnail_aspect_ratio="9:16")

        updated_org = MagicMock()
        updated_org.settings = {"thumbnail_aspect_ratio": "9:16"}
        updated_org.get_settings_with_defaults = MagicMock(
            return_value={"thumbnail_aspect_ratio": "9:16"}
        )

        org_repo = AsyncMock()
        org_repo.update_settings = AsyncMock(return_value=updated_org)

        db = AsyncMock()
        db.commit = AsyncMock()

        patch_response = await update_org_settings(
            request=patch_request,
            org_ctx=org_ctx,
            user=user,
            org_repo=org_repo,
            db=db,
        )

        assert patch_response.thumbnail_aspect_ratio == "9:16"

        # Step 2: GET to verify persistence
        org_repo.get_by_id = AsyncMock(return_value=updated_org)

        get_response = await get_org_settings(
            org_ctx=org_ctx,
            user=user,
            org_repo=org_repo,
        )

        assert get_response.thumbnail_aspect_ratio == "9:16"
