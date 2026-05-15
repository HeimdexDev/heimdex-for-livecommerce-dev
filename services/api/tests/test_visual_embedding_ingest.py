"""Tests for visual embedding ingestion through the enrich pipeline.

Verifies that:
1. EnrichSceneUpdate accepts visual_embedding field
2. visual_embedding is passed through to OpenSearch partial updates
3. visual_embedding does NOT trigger text embedding recomputation
4. Other enrichment fields still work correctly alongside visual_embedding
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.ingest.schemas import EnrichSceneUpdate, EnrichScenesRequest


class TestEnrichSceneUpdateSchema:
    """Test the EnrichSceneUpdate schema with visual_embedding field."""

    def test_visual_embedding_optional(self) -> None:
        update = EnrichSceneUpdate(scene_id="test_scene_001")
        assert update.visual_embedding is None

    def test_visual_embedding_accepts_list(self) -> None:
        vec = [0.1] * 768
        update = EnrichSceneUpdate(scene_id="test_scene_001", visual_embedding=vec)
        assert update.visual_embedding == vec
        assert len(update.visual_embedding) == 768

    def test_visual_embedding_with_other_fields(self) -> None:
        """visual_embedding should coexist with text enrichment fields."""
        vec = [0.5] * 768
        update = EnrichSceneUpdate(
            scene_id="test_scene_001",
            transcript_raw="안녕하세요",
            visual_embedding=vec,
        )
        assert update.transcript_raw == "안녕하세요"
        assert update.visual_embedding == vec

    def test_visual_embedding_only_no_text_fields(self) -> None:
        """visual_embedding alone — no text fields set."""
        vec = [0.2] * 768
        update = EnrichSceneUpdate(
            scene_id="test_scene_001",
            visual_embedding=vec,
        )
        assert update.transcript_raw is None
        assert update.ocr_text_raw is None
        assert update.scene_caption is None
        assert update.visual_embedding == vec

    def test_enrichment_request_with_visual_embedding(self) -> None:
        vec = [0.3] * 768
        request = EnrichScenesRequest(
            video_id="vid_001",
            scenes=[
                EnrichSceneUpdate(scene_id="scene_001", visual_embedding=vec),
                EnrichSceneUpdate(scene_id="scene_002", transcript_raw="텍스트"),
            ],
        )
        assert request.scenes[0].visual_embedding == vec
        assert request.scenes[1].visual_embedding is None


class TestEnrichServiceVisualEmbedding:
    """Test that enrich_scenes correctly handles visual_embedding."""

    @pytest.fixture
    def mock_scene_opensearch(self) -> MagicMock:
        client = MagicMock()
        client.mget_scenes = AsyncMock()
        client.bulk_partial_update_scenes = AsyncMock()
        return client

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        return MagicMock()

    @pytest.mark.asyncio
    async def test_visual_embedding_passthrough(
        self, mock_session: MagicMock, mock_scene_opensearch: MagicMock
    ) -> None:
        """visual_embedding should be stored directly without text embedding recomputation."""
        from uuid import UUID
        from app.modules.ingest.service import SceneIngestService

        org_id = UUID("4d20264c-c440-4d69-8613-7d7558ea386b")
        vec = [0.1] * 768

        mock_scene_opensearch.mget_scenes.return_value = {
            f"{org_id}:scene_001": {
                "transcript_raw": "기존 텍스트",
                "ocr_text_raw": "",
                "scene_caption": "",
            }
        }

        request = EnrichScenesRequest(
            video_id="vid_001",
            scenes=[EnrichSceneUpdate(scene_id="scene_001", visual_embedding=vec)],
        )

        service = SceneIngestService(mock_session, mock_scene_opensearch)
        result = await service.enrich_scenes(request, org_id)

        assert result["updated_count"] == 1
        assert result["skipped_count"] == 0

        # Check the partial update was called with visual_embedding
        call_args = mock_scene_opensearch.bulk_partial_update_scenes.call_args
        updates = call_args[0][0]
        assert len(updates) == 1
        doc_id, partial = updates[0]
        assert partial["visual_embedding"] == vec

    @pytest.mark.asyncio
    async def test_visual_embedding_no_text_recomputation(
        self, mock_session: MagicMock, mock_scene_opensearch: MagicMock
    ) -> None:
        """visual_embedding alone should NOT trigger text embedding recomputation."""
        from uuid import UUID
        from app.modules.ingest.service import SceneIngestService

        org_id = UUID("4d20264c-c440-4d69-8613-7d7558ea386b")
        vec = [0.2] * 768

        mock_scene_opensearch.mget_scenes.return_value = {
            f"{org_id}:scene_001": {
                "transcript_raw": "기존 트랜스크립트",
                "ocr_text_raw": "",
                "scene_caption": "",
            }
        }

        request = EnrichScenesRequest(
            video_id="vid_001",
            scenes=[EnrichSceneUpdate(scene_id="scene_001", visual_embedding=vec)],
        )

        service = SceneIngestService(mock_session, mock_scene_opensearch)

        with patch("app.modules.ingest.service.get_passage_embeddings_batch") as mock_embed:
            await service.enrich_scenes(request, org_id)
            # Text embedding batch should NOT be called because only visual_embedding changed
            mock_embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_visual_embedding_with_transcript_triggers_text_recomputation(
        self, mock_session: MagicMock, mock_scene_opensearch: MagicMock
    ) -> None:
        """When visual_embedding AND transcript are both set, text embedding SHOULD recompute."""
        from uuid import UUID
        from app.modules.ingest.service import SceneIngestService

        org_id = UUID("4d20264c-c440-4d69-8613-7d7558ea386b")
        vec = [0.3] * 768

        mock_scene_opensearch.mget_scenes.return_value = {
            f"{org_id}:scene_001": {
                "transcript_raw": "",
                "ocr_text_raw": "",
                "scene_caption": "",
            }
        }

        request = EnrichScenesRequest(
            video_id="vid_001",
            scenes=[
                EnrichSceneUpdate(
                    scene_id="scene_001",
                    transcript_raw="새 트랜스크립트 텍스트",
                    visual_embedding=vec,
                )
            ],
        )

        service = SceneIngestService(mock_session, mock_scene_opensearch)

        with patch("app.modules.ingest.service.get_passage_embeddings_batch") as mock_embed:
            mock_embed.return_value = [[0.5] * 1024]
            await service.enrich_scenes(request, org_id)
            # Text embedding SHOULD be called because transcript changed
            mock_embed.assert_called_once()

        # Both embeddings should be in the partial update
        call_args = mock_scene_opensearch.bulk_partial_update_scenes.call_args
        updates = call_args[0][0]
        doc_id, partial = updates[0]
        assert partial["visual_embedding"] == vec
        assert "embedding_vector" in partial  # Text embedding recomputed
