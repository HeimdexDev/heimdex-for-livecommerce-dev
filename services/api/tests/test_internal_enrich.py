import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.ingest.internal_router import _verify_internal_token, internal_enrich_scenes
from app.modules.ingest.schemas import EnrichSceneUpdate, EnrichScenesRequest
from app.modules.ingest.service import SceneIngestService, generate_tags
from app.modules.orgs.repository import OrgRepository


def _mock_no_scene_overrides(session: AsyncMock) -> None:
    """Scene enrichment now protects user overrides via a DB lookup."""
    result = MagicMock()
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)


class TestInternalEnrichService:
    @pytest.fixture
    def mock_scene_client(self):
        client = MagicMock()
        client.mget_scenes = AsyncMock()
        client.bulk_index_scenes = AsyncMock()
        client.bulk_partial_update_scenes = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_db_session, mock_scene_client):
        _mock_no_scene_overrides(mock_db_session)
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

        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.1] * 1024]):
            result = await service.enrich_scenes(request, org_id)

        assert result["updated_count"] == 1
        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert partial["transcript_raw"] == "hello world"
        assert partial["speech_segment_count"] == 2
        assert "embedding_vector" in partial
        # Partial update should NOT contain fields not being enriched
        assert "scene_caption" not in partial
        assert "ocr_text_raw" not in partial

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

        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.1] * 1024]):
            await service.enrich_scenes(request, org_id)

        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert partial["ocr_text_raw"] == "50% OFF"
        assert partial["ocr_text_norm"] == "50% off"
        # Partial update should NOT contain transcript or caption
        assert "transcript_raw" not in partial
        assert "scene_caption" not in partial

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

        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.7] * 1024]) as mock_embed:
            result = await service.enrich_scenes(request, org_id)

        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert partial["scene_caption"] == "a person holding product"
        # Caption-only enrichment should NOT touch transcript or OCR raw fields
        assert "transcript_raw" not in partial
        assert "ocr_text_raw" not in partial
        # AD-2: caption triggers embedding recomputation
        assert "embedding_vector" in partial
        mock_embed.assert_called_once()
    @pytest.mark.asyncio
    async def test_partial_update_only_contains_enriched_fields(self, service, mock_scene_client):
        """Partial updates should contain ONLY fields from this enrichment,
        preventing concurrent workers from overwriting each other's data."""
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

        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.1] * 1024]):
            await service.enrich_scenes(request, org_id)

        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert partial["transcript_raw"] == "new text"
        # These fields should NOT be in the partial update — they belong to
        # other enrichment workers and must not be overwritten.
        assert "ocr_text_raw" not in partial
        assert "scene_caption" not in partial

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
        mock_scene_client.bulk_partial_update_scenes.assert_not_awaited()
        mock_warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_embedding_recomputed_from_merged_text(self, service, mock_scene_client):
        """When OCR is enriched, embedding should combine existing transcript + new OCR."""
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

        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.2] * 1024]) as mock_embed:
            await service.enrich_scenes(request, org_id)

        # Embedding text should combine existing transcript + new OCR
        mock_embed.assert_called_once_with(["hello sale"])

    @pytest.mark.asyncio
    async def test_concurrent_enrichment_safety(self, service, mock_scene_client):
        """Caption-only enrichment should not overwrite existing transcript/OCR.

        This is the race condition fix: previously, the enrich service would
        read the full doc, normalize ALL fields, and write the full doc back.
        If STT ran concurrently, it could overwrite caption data with stale
        values from its own read.  With partial updates, each worker only
        writes its own fields.

        AD-2 update: caption enrichment now triggers embedding recomputation
        (caption-first: caption + transcript[:500] + ocr[:200]).
        """
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"

        # Caption enrichment only sends scene_caption
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id=scene_id, scene_caption="라이브 방송 중 상품 소개")],
        )

        # Existing doc already has transcript and OCR from other workers
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {
                "scene_id": scene_id,
                "transcript_raw": "안녕하세요 여러분",
                "transcript_norm": "안녕하세요 여러분",
                "ocr_text_raw": "30% 할인",
                "scene_caption": "",
                "embedding_vector": [0.5] * 1024,
            }
        }

        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.9] * 1024]) as mock_embed:
            result = await service.enrich_scenes(request, org_id)

        assert result["updated_count"] == 1
        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]

        # Caption enrichment writes caption + ingest_time + recomputed embedding
        assert partial["scene_caption"] == "라이브 방송 중 상품 소개"
        assert "ingest_time" in partial

        # Must NOT touch transcript or OCR raw fields (those belong to other workers)
        assert "transcript_raw" not in partial
        assert "transcript_norm" not in partial
        assert "ocr_text_raw" not in partial

        # AD-2: caption triggers embedding recomputation with caption-first ordering
        assert "embedding_vector" in partial
        assert partial["embedding_vector"] == [0.9] * 1024
        # Embedding text should be: caption + transcript + ocr
        mock_embed.assert_called_once()

class TestInternalEnrichEndpoint:
    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        with patch("app.dependencies.get_settings") as mock_settings:
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
        mock_org_repo = AsyncMock(spec=OrgRepository)
        mock_org_repo.get_by_id.return_value = None
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(scene_id="vid1_scene_0", transcript_raw="hello")],
        )

        with patch("app.modules.ingest.internal_router.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_max_scenes = 100
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await internal_enrich_scenes(
                    request=request,
                    x_heimdex_org_id=str(org_id),
                    verified_service_id="drive-worker",
                    db=mock_db,
                    org_repo=mock_org_repo,
                    ingest_service=mock_ingest_service,
                )
            assert exc_info.value.status_code == 404


class TestGenerateTags:
    def test_korean_transcript_produces_keyword_tags(self):
        kw, _ = generate_tags("지금 바로 할인 가격으로 구매하세요", "")
        assert "price" in kw
        assert "cta" in kw

    def test_korean_transcript_produces_product_tags(self):
        _, pt = generate_tags("이 스킨케어 세럼은 수분크림과 함께 사용하세요", "")
        assert "skincare" in pt

    def test_caption_text_produces_tags(self):
        kw, pt = generate_tags("", "호스트가 립스틱을 바르며 할인 쿠폰을 설명하고 있다")
        assert "price" in kw or "coupon" in kw
        assert "makeup" in pt

    def test_combined_transcript_and_caption(self):
        kw, pt = generate_tags(
            "배송은 무료배송입니다",
            "호스트가 샴푸 제품을 보여주고 있다",
        )
        assert "delivery" in kw
        assert "haircare" in pt

    def test_empty_inputs_return_empty_lists(self):
        kw, pt = generate_tags("", "")
        assert kw == []
        assert pt == []

    def test_no_matching_keywords_return_empty(self):
        kw, pt = generate_tags("오늘 날씨가 좋습니다", "")
        assert kw == []
        assert pt == []

    def test_tags_are_sorted(self):
        kw, _ = generate_tags("지금 구매하세요 할인 가격 쿠폰 배송", "")
        assert kw == sorted(kw)


class TestEnrichTagGeneration:
    @pytest.fixture
    def mock_scene_client(self):
        client = MagicMock()
        client.mget_scenes = AsyncMock()
        client.bulk_partial_update_scenes = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_db_session, mock_scene_client):
        _mock_no_scene_overrides(mock_db_session)
        return SceneIngestService(mock_db_session, mock_scene_client)

    @pytest.mark.asyncio
    async def test_stt_enrichment_generates_keyword_tags(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(
                scene_id=scene_id,
                transcript_raw="지금 바로 할인 가격으로 구매하세요",
            )],
        )
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {"scene_id": scene_id, "transcript_raw": "", "ocr_text_raw": "", "scene_caption": ""}
        }
        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.1] * 1024]):
            await service.enrich_scenes(request, org_id)

        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert "keyword_tags" in partial
        assert "price" in partial["keyword_tags"]
        assert "cta" in partial["keyword_tags"]

    @pytest.mark.asyncio
    async def test_caption_enrichment_generates_product_tags(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(
                scene_id=scene_id,
                scene_caption="호스트가 립스틱을 바르고 있다",
            )],
        )
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {"scene_id": scene_id, "transcript_raw": "", "ocr_text_raw": "", "scene_caption": ""}
        }
        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.1] * 1024]):
            await service.enrich_scenes(request, org_id)

        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert "product_tags" in partial
        assert "makeup" in partial["product_tags"]

    @pytest.mark.asyncio
    async def test_enrichment_combines_existing_and_new_text_for_tags(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(
                scene_id=scene_id,
                scene_caption="호스트가 샴푸를 보여주고 있다",
            )],
        )
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {
                "scene_id": scene_id,
                "transcript_raw": "지금 할인 가격입니다",
                "ocr_text_raw": "",
                "scene_caption": "",
            }
        }
        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.1] * 1024]):
            await service.enrich_scenes(request, org_id)

        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert "keyword_tags" in partial
        assert "price" in partial["keyword_tags"]
        assert "product_tags" in partial
        assert "haircare" in partial["product_tags"]

    @pytest.mark.asyncio
    async def test_no_tags_when_text_has_no_keywords(self, service, mock_scene_client):
        org_id = uuid4()
        scene_id = "vid1_scene_0"
        doc_id = f"{org_id}:{scene_id}"
        request = EnrichScenesRequest(
            video_id="vid1",
            scenes=[EnrichSceneUpdate(
                scene_id=scene_id,
                transcript_raw="오늘 날씨가 좋습니다",
            )],
        )
        mock_scene_client.mget_scenes.return_value = {
            doc_id: {"scene_id": scene_id, "transcript_raw": "", "ocr_text_raw": "", "scene_caption": ""}
        }
        with patch("app.modules.ingest.service.get_passage_embeddings_batch", return_value=[[0.1] * 1024]):
            await service.enrich_scenes(request, org_id)

        updates = mock_scene_client.bulk_partial_update_scenes.call_args[0][0]
        _, partial = updates[0]
        assert "keyword_tags" not in partial
        assert "product_tags" not in partial
