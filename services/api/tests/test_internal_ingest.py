import hmac
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.ingest.internal_router import internal_ingest_scenes, _verify_internal_token
from app.modules.orgs.repository import OrgRepository


class TestVerifyInternalToken:
    @pytest.mark.asyncio
    async def test_valid_token_accepted(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "secret-key-123"
            result = await _verify_internal_token("Bearer secret-key-123")
            assert result == "secret-key-123"

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "correct-key"
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Bearer wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_bearer_prefix_returns_401(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "key"
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Basic key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unconfigured_key_returns_503(self):
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = ""
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Bearer anything")
            assert exc_info.value.status_code == 503


class TestInternalIngestOrgValidation:
    @pytest.mark.asyncio
    async def test_unknown_org_returns_404(self):
        org_id = uuid4()
        mock_db = AsyncMock()
        mock_ingest_service = AsyncMock()
        org_repo = AsyncMock(spec=OrgRepository)
        org_repo.get_by_id.return_value = None

        with patch("app.modules.ingest.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_max_scenes = 100
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await internal_ingest_scenes(
                    request=MagicMock(scenes=[]),
                    x_heimdex_org_id=str(org_id),
                    verified_service_id="legacy",  # F1 Phase 3: was _token; "legacy" simulates the backward-compat path
                    db=mock_db,
                    org_repo=org_repo,
                    ingest_service=mock_ingest_service,
                )
            assert exc_info.value.status_code == 404
            assert "not found" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_valid_org_proceeds_to_ingest(self):
        org_id = uuid4()
        lib_id = uuid4()
        mock_db = AsyncMock()
        mock_ingest_service = AsyncMock()
        mock_ingest_service.ingest_scenes.return_value = {
            "video_id": "vid1",
            "indexed_count": 1,
        }
        org_repo = AsyncMock(spec=OrgRepository)
        org_repo.get_by_id.return_value = MagicMock(id=org_id)

        from app.modules.ingest.schemas import IngestScenesRequest, IngestSceneDocument
        request = IngestScenesRequest(
            video_id="vid1",
            library_id=lib_id,
            total_duration_ms=5000,
            scenes=[
                IngestSceneDocument(
                    scene_id="vid1_scene_0",
                    index=0,
                    start_ms=0,
                    end_ms=5000,
                ),
            ],
        )

        with patch("app.modules.ingest.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_max_scenes = 100
            result = await internal_ingest_scenes(
                request=request,
                x_heimdex_org_id=str(org_id),
                verified_service_id="legacy",  # F1 Phase 3: was _token; "legacy" simulates the backward-compat path
                db=mock_db,
                org_repo=org_repo,
                ingest_service=mock_ingest_service,
            )
            assert result.indexed_count == 1
            mock_ingest_service.ingest_scenes.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_400(self):
        mock_db = AsyncMock()
        mock_ingest_service = AsyncMock()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await internal_ingest_scenes(
                request=MagicMock(scenes=[]),
                x_heimdex_org_id="not-a-uuid",
                verified_service_id="legacy",  # F1 Phase 3: was _token; "legacy" simulates the backward-compat path
                db=mock_db,
                ingest_service=mock_ingest_service,
            )
        assert exc_info.value.status_code == 400
