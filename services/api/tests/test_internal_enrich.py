import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.ingest.internal_router import _verify_internal_token, internal_enrich_scenes
from app.modules.ingest.schemas import EnrichSceneUpdate, EnrichScenesRequest
from app.modules.ingest.service import SceneIngestService


class TestInternalEnrichService:
    @pytest.fixture
    def mock_scene_client(self):
        client = MagicMock()
        client.mget_scenes = AsyncMock()
        client.bulk_index_scenes = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_db_session, mock_scene_client):
        return SceneIngestService(mock_db_session, mock_scene_client)

    @pytest.mark.asyncio
    async def test_enrich_with_stt_merges_correctly(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id=scene_id, transcript_raw="hello world", speech_segment_count=2)],
        )

        mock_scene_client.mget_scenes.return_value = {
            doc_id: {
                "scene_id": scene_id,
                "transcript_raw": "",
                "ocr_text_raw": "SALE",
                "scene_caption": "old caption",
            }
        }

        with patch("app.modules.ingest.service.get_passage_embedding", return_value=[0.1] * 1024):
            result = await service.enrich_scenes(request, org_id)

        assert result["updated_count"] == 1
        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, merged = docs[0]
        assert merged["transcript_raw"] == "hello world"
        assert merged["speech_segment_count"] == 2
        assert merged["ocr_text_raw"] == "SALE"
        assert "embedding_vector" in merged

    @pytest.mark.asyncio
    async def test_enrich_with_ocr_merges_correctly(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id=scene_id, ocr_text_raw="50% OFF", ocr_char_count=7)],
        )

        mock_scene_client.mget_scenes.return_value = {
            doc_id: {
                "scene_id": scene_id,
                "transcript_raw": "hello",
                "ocr_text_raw": "",
                "scene_caption": "caption",
            }
        }

        with patch("app.modules.ingest.service.get_passage_embedding", return_value=[0.1] * 1024):
            await service.enrich_scenes(request, org_id)

        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, merged = docs[0]
        assert merged["ocr_text_raw"] == "50% OFF"
        assert merged["ocr_text_norm"] == "50% off"
        assert merged["transcript_raw"] == "hello"

    @pytest.mark.asyncio
    async def test_enrich_with_caption_merges_correctly(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id=scene_id, scene_caption="A person holding product")],
        )

        mock_scene_client.mget_scenes.return_value = {
            doc_id: {
                "scene_id": scene_id,
                "transcript_raw": "hello",
                "ocr_text_raw": "sale",
                "scene_caption": "",
            }
        }

        with patch("app.modules.ingest.service.get_passage_embedding", return_value=[0.1] * 1024):
            await service.enrich_scenes(request, org_id)

        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, merged = docs[0]
        assert merged["scene_caption"] == "a person holding product"
        assert merged["transcript_raw"] == "hello"
        assert merged["ocr_text_raw"] == "sale"

    @pytest.mark.asyncio
    async def test_partial_merge_preserves_unset_fields(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id=scene_id, transcript_raw="new text")],
        )

        mock_scene_client.mget_scenes.return_value = {
            doc_id: {
                "scene_id": scene_id,
                "transcript_raw": "old text",
                "speech_segment_count": 3,
                "ocr_text_raw": "original ocr",
                "scene_caption": "original caption",
            }
        }

        with patch("app.modules.ingest.service.get_passage_embedding", return_value=[0.1] * 1024):
            await service.enrich_scenes(request, org_id)

        docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, merged = docs[0]
        assert merged["transcript_raw"] == "new text"
        assert merged["ocr_text_raw"] == "original ocr"
        assert merged["scene_caption"] == "original caption"

    @pytest.mark.asyncio
    async def test_scene_not_found_skipped_with_warning(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id=scene_id, transcript_raw="new text")],
        )

        mock_scene_client.mget_scenes.return_value = {}

        with patch("app.modules.ingest.service.logger.warning") as mock_warning:
            result = await service.enrich_scenes(request, org_id)

        assert result["updated_count"] == 0
        assert result["skipped_count"] == 1
        mock_scene_client.bulk_index_scenes.assert_not_awaited()
        mock_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_embedding_recomputed_from_merged_text(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id=scene_id, ocr_text_raw="SALE", ocr_char_count=4)],
        )

        mock_scene_client.mget_scenes.return_value = {
            doc_id: {
                "scene_id": scene_id,
                "transcript_raw": "Hello",
                "ocr_text_raw": "",
                "scene_caption": "",
            }
        }

        with patch("app.modules.ingest.service.get_passage_embedding", return_value=[0.2] * 1024) as mock_embed:
            await service.enrich_scenes(request, org_id)

        mock_embed.assert_called_once_with("hello sale")


class TestInternalEnrichEndpoint:
    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        with patch("app.modules.ingest.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.drive_internal_api_key = "correct-key"
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await _verify_internal_token("Bearer wrong-key")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_org_returns_404(self):
        org_id = uuid4()
        mock_db = AsyncMock()
        mock_ingest_service = AsyncMock()
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id="vid1_scene_0", transcript_raw="hello")],
        )

        with patch("app.modules.ingest.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_max_scenes = 100
            with patch("app.modules.orgs.repository.OrgRepository") as mock_org_repo:
                mock_repo = mock_org_repo.return_value
                mock_repo.get_by_id = AsyncMock(return_value=None)
                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await internal_enrich_scenes(
                        request=request,
                        x_heimdex_org_id=str(org_id),
                        _token="valid",
                        db=mock_db,
                        ingest_service=mock_ingest_service,
                    )
                assert exc_info.value.status_code == 404
