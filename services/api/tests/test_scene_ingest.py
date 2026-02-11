"""
Unit tests for the agent scene ingestion module.

Tests cover:
1. IngestScenesRequest/IngestSceneDocument schema validation
2. verify_agent_token auth dependency (valid, invalid, disabled)
3. SceneIngestService.ingest_scenes (happy path, empty transcript, library validation)
4. Router-level behavior (max scenes cap, error mapping)

Run with: pytest tests/test_scene_ingest.py -v
"""
import hmac
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

from app.modules.ingest.schemas import (
    IngestSceneDocument,
    IngestScenesRequest,
    IngestScenesResponse,
)
from app.modules.ingest.service import SceneIngestService


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------
class TestIngestScenesSchemas:
    def test_valid_ingest_scene_document(self):
        doc = IngestSceneDocument(
            scene_id="vid123_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            transcript_raw="Hello world",
            speech_segment_count=2,
        )
        assert doc.scene_id == "vid123_scene_0"
        assert doc.start_ms == 0
        assert doc.end_ms == 5000
        assert doc.source_type == "gdrive"
        assert doc.required_drive_nickname is None
        assert doc.capture_time is None

    def test_ingest_scene_document_defaults(self):
        doc = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=1000,
        )
        assert doc.transcript_raw == ""
        assert doc.speech_segment_count == 0
        assert doc.people_cluster_ids == []
        assert doc.keyframe_timestamp_ms == 0
        assert doc.keyword_tags == []
        assert doc.product_tags == []
        assert doc.product_entities == []

    def test_ingest_scene_document_with_tags(self):
        doc = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            keyword_tags=["cta", "price"],
            product_tags=["skincare"],
            product_entities=["세럼", "수분크림"],
        )
        assert doc.keyword_tags == ["cta", "price"]
        assert doc.product_tags == ["skincare"]
        assert doc.product_entities == ["세럼", "수분크림"]

    def test_ingest_scene_document_end_before_start_rejected(self):
        with pytest.raises(Exception):
            IngestSceneDocument(
                scene_id="vid_scene_0",
                index=0,
                start_ms=5000,
                end_ms=1000,
            )

    def test_ingest_scene_document_negative_start_rejected(self):
        with pytest.raises(Exception):
            IngestSceneDocument(
                scene_id="vid_scene_0",
                index=0,
                start_ms=-1,
                end_ms=1000,
            )

    def test_ingest_scene_document_with_source_metadata(self):
        now = datetime.now(timezone.utc)
        doc = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            source_type="removable_disk",
            required_drive_nickname="USB-cam-1",
            capture_time=now,
        )
        assert doc.source_type == "removable_disk"
        assert doc.required_drive_nickname == "USB-cam-1"
        assert doc.capture_time == now

    def test_valid_ingest_request(self):
        lib_id = uuid4()
        req = IngestScenesRequest(
            video_id="abc123",
            library_id=lib_id,
            pipeline_version="1.0",
            model_version="whisper-v3",
            total_duration_ms=60000,
            scenes=[
                IngestSceneDocument(
                    scene_id="abc123_scene_0",
                    index=0,
                    start_ms=0,
                    end_ms=30000,
                    transcript_raw="Scene one transcript",
                ),
                IngestSceneDocument(
                    scene_id="abc123_scene_1",
                    index=1,
                    start_ms=30000,
                    end_ms=60000,
                    transcript_raw="Scene two transcript",
                ),
            ],
        )
        assert req.video_id == "abc123"
        assert req.library_id == lib_id
        assert len(req.scenes) == 2

    def test_ingest_request_empty_video_id_rejected(self):
        with pytest.raises(Exception):
            IngestScenesRequest(
                video_id="",
                library_id=uuid4(),
                scenes=[],
            )

    def test_ingest_request_defaults(self):
        req = IngestScenesRequest(
            video_id="vid1",
            library_id=uuid4(),
            scenes=[],
        )
        assert req.video_title == ""
        assert req.pipeline_version == ""
        assert req.model_version == ""
        assert req.total_duration_ms == 0

    def test_ingest_response(self):
        resp = IngestScenesResponse(
            indexed_count=5,
            video_id="abc123",
            skipped_count=0,
        )
        assert resp.indexed_count == 5
        assert resp.video_id == "abc123"
        assert resp.skipped_count == 0


# ---------------------------------------------------------------------------
# Auth dependency tests
# ---------------------------------------------------------------------------
class TestVerifyAgentToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_org_context(self):
        from app.modules.ingest.auth import verify_agent_token

        org_id = uuid4()
        org_ctx = MagicMock()
        org_ctx.org_id = org_id
        org_ctx.org_slug = "testorg"

        credentials = MagicMock()
        credentials.credentials = "dev-agent-key-change-in-production"

        with patch("app.modules.ingest.auth.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_enabled = True
            mock_settings.return_value.agent_api_key = "dev-agent-key-change-in-production"

            result = await verify_agent_token(
                credentials=credentials,
                org_ctx=org_ctx,
            )

        assert result.org_id == org_id
        assert result.org_slug == "testorg"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        from fastapi import HTTPException
        from app.modules.ingest.auth import verify_agent_token

        org_ctx = MagicMock()
        org_ctx.org_id = uuid4()
        org_ctx.org_slug = "testorg"

        credentials = MagicMock()
        credentials.credentials = "wrong-token"

        with patch("app.modules.ingest.auth.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_enabled = True
            mock_settings.return_value.agent_api_key = "correct-token"

            with pytest.raises(HTTPException) as exc_info:
                await verify_agent_token(
                    credentials=credentials,
                    org_ctx=org_ctx,
                )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_disabled_ingestion_raises_403(self):
        from fastapi import HTTPException
        from app.modules.ingest.auth import verify_agent_token

        org_ctx = MagicMock()
        org_ctx.org_id = uuid4()
        org_ctx.org_slug = "testorg"

        credentials = MagicMock()
        credentials.credentials = "dev-agent-key-change-in-production"

        with patch("app.modules.ingest.auth.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_enabled = False
            mock_settings.return_value.agent_api_key = "dev-agent-key-change-in-production"

            with pytest.raises(HTTPException) as exc_info:
                await verify_agent_token(
                    credentials=credentials,
                    org_ctx=org_ctx,
                )

        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# SceneIngestService tests
# ---------------------------------------------------------------------------
class TestSceneIngestService:
    @pytest.fixture
    def mock_scene_client(self):
        client = MagicMock()
        client.bulk_index_scenes = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_db_session, mock_scene_client):
        return SceneIngestService(mock_db_session, mock_scene_client)

    def _make_request(
        self,
        video_id: str = "vid_abc",
        video_title: str = "Sample Video",
        library_id: UUID | None = None,
        scenes: list[IngestSceneDocument] | None = None,
    ) -> IngestScenesRequest:
        if scenes is None:
            scenes = [
                IngestSceneDocument(
                    scene_id=f"{video_id}_scene_0",
                    index=0,
                    start_ms=0,
                    end_ms=10000,
                    transcript_raw="안녕하세요 이것은 테스트입니다",
                    speech_segment_count=2,
                ),
            ]
        return IngestScenesRequest(
            video_id=video_id,
            video_title=video_title,
            library_id=library_id or uuid4(),
            pipeline_version="1.0",
            model_version="whisper-v3",
            total_duration_ms=30000,
            scenes=scenes,
        )

    @pytest.mark.asyncio
    async def test_ingest_happy_path(self, service, mock_db_session, mock_scene_client):
        """Happy path: valid library, non-empty transcript -> normalized + embedded + indexed."""
        org_id = uuid4()
        lib_id = uuid4()
        request = self._make_request(library_id=lib_id)

        # Mock library lookup to return a library
        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_lib.org_id = org_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_embedding = [0.1] * 1024
        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[mock_embedding],
        ):
            result = await service.ingest_scenes(request, org_id)

        assert result["indexed_count"] == 1
        assert result["video_id"] == "vid_abc"
        assert result["skipped_count"] == 0

        # Verify bulk_index_scenes was called with correct doc_id format
        mock_scene_client.bulk_index_scenes.assert_awaited_once()
        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        assert len(call_args) == 1

        doc_id, doc = call_args[0]
        assert doc_id == f"{org_id}:vid_abc_scene_0"
        assert doc["org_id"] == str(org_id)
        assert doc["library_id"] == str(lib_id)
        assert doc["video_id"] == "vid_abc"
        assert doc["video_title"] == "Sample Video"
        assert doc["scene_id"] == "vid_abc_scene_0"
        assert doc["transcript_norm"] != ""  # Normalized
        assert "embedding_vector" in doc  # Has embedding for non-empty transcript

    @pytest.mark.asyncio
    async def test_ingest_empty_transcript_omits_embedding(
        self, service, mock_db_session, mock_scene_client
    ):
        """Empty transcript: scene indexed but embedding_vector omitted."""
        org_id = uuid4()
        lib_id = uuid4()

        scene = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            transcript_raw="",
            speech_segment_count=0,
        )
        request = self._make_request(library_id=lib_id, scenes=[scene])

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[],
        ) as mock_embed:
            result = await service.ingest_scenes(request, org_id)

        assert result["indexed_count"] == 1

        # Verify no embedding call was made (empty transcript)
        mock_embed.assert_not_called()

        # Verify document has no embedding_vector
        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = call_args[0]
        assert "embedding_vector" not in doc
        assert doc["transcript_norm"] == ""
        assert doc["transcript_char_count"] == 0

    @pytest.mark.asyncio
    async def test_ingest_multiple_scenes_batch_embeds(
        self, service, mock_db_session, mock_scene_client
    ):
        """Multiple scenes with transcripts should batch-embed efficiently."""
        org_id = uuid4()
        lib_id = uuid4()

        scenes = [
            IngestSceneDocument(
                scene_id=f"vid_scene_{i}",
                index=i,
                start_ms=i * 10000,
                end_ms=(i + 1) * 10000,
                transcript_raw=f"Transcript for scene {i}",
                speech_segment_count=1,
            )
            for i in range(3)
        ]
        request = self._make_request(library_id=lib_id, scenes=scenes)

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_embeddings = [[0.1] * 1024 for _ in range(3)]
        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=mock_embeddings,
        ) as mock_embed:
            result = await service.ingest_scenes(request, org_id)

        assert result["indexed_count"] == 3
        # Batch embed called once with 3 texts
        mock_embed.assert_called_once()
        texts_arg = mock_embed.call_args[0][0]
        assert len(texts_arg) == 3

    @pytest.mark.asyncio
    async def test_ingest_invalid_library_raises_value_error(
        self, service, mock_db_session, mock_scene_client
    ):
        """library_id not found for org -> ValueError."""
        org_id = uuid4()
        request = self._make_request()

        # Library not found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="not found or does not belong"):
            await service.ingest_scenes(request, org_id)

        # Verify no indexing happened
        mock_scene_client.bulk_index_scenes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ingest_mixed_empty_and_nonempty_transcripts(
        self, service, mock_db_session, mock_scene_client
    ):
        """Mix of empty and non-empty transcripts: only non-empty get embeddings."""
        org_id = uuid4()
        lib_id = uuid4()

        scenes = [
            IngestSceneDocument(
                scene_id="vid_scene_0",
                index=0,
                start_ms=0,
                end_ms=5000,
                transcript_raw="",  # Empty
            ),
            IngestSceneDocument(
                scene_id="vid_scene_1",
                index=1,
                start_ms=5000,
                end_ms=10000,
                transcript_raw="Hello world transcript",  # Non-empty
            ),
            IngestSceneDocument(
                scene_id="vid_scene_2",
                index=2,
                start_ms=10000,
                end_ms=15000,
                transcript_raw="",  # Empty
            ),
        ]
        request = self._make_request(library_id=lib_id, scenes=scenes)

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_embedding = [[0.1] * 1024]
        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=mock_embedding,
        ) as mock_embed:
            result = await service.ingest_scenes(request, org_id)

        assert result["indexed_count"] == 3

        # Only 1 non-empty transcript -> batch called with 1 text
        mock_embed.assert_called_once()
        texts = mock_embed.call_args[0][0]
        assert len(texts) == 1

        # Check documents
        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        assert len(call_args) == 3

        # Scene 0: no embedding
        _, doc0 = call_args[0]
        assert "embedding_vector" not in doc0

        # Scene 1: has embedding
        _, doc1 = call_args[1]
        assert "embedding_vector" in doc1

        # Scene 2: no embedding
        _, doc2 = call_args[2]
        assert "embedding_vector" not in doc2

    @pytest.mark.asyncio
    async def test_ingest_stamps_org_id_and_ingest_time(
        self, service, mock_db_session, mock_scene_client
    ):
        """Every document should have org_id stamped and ingest_time set."""
        org_id = uuid4()
        lib_id = uuid4()
        request = self._make_request(library_id=lib_id)

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            await service.ingest_scenes(request, org_id)

        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = call_args[0]

        assert doc["org_id"] == str(org_id)
        assert doc["ingest_time"] is not None
        # ingest_time should be a valid ISO timestamp
        datetime.fromisoformat(doc["ingest_time"])

    @pytest.mark.asyncio
    async def test_ingest_empty_scenes_list(
        self, service, mock_db_session, mock_scene_client
    ):
        """Empty scenes list should still succeed with 0 indexed."""
        org_id = uuid4()
        lib_id = uuid4()
        request = self._make_request(library_id=lib_id, scenes=[])

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result = await service.ingest_scenes(request, org_id)

        assert result["indexed_count"] == 0
        assert result["video_id"] == "vid_abc"

    @pytest.mark.asyncio
    async def test_ingest_preserves_people_cluster_ids(
        self, service, mock_db_session, mock_scene_client
    ):
        """people_cluster_ids should be passed through to the indexed document."""
        org_id = uuid4()
        lib_id = uuid4()

        scene = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            transcript_raw="Test",
            people_cluster_ids=["cluster_001", "cluster_002"],
        )
        request = self._make_request(library_id=lib_id, scenes=[scene])

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            await service.ingest_scenes(request, org_id)

        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = call_args[0]
        assert doc["people_cluster_ids"] == ["cluster_001", "cluster_002"]

    @pytest.mark.asyncio
    async def test_ingest_preserves_keyword_and_product_tags(
        self, service, mock_db_session, mock_scene_client
    ):
        """keyword_tags, product_tags, product_entities should be passed through to indexed doc."""
        org_id = uuid4()
        lib_id = uuid4()

        scene = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            transcript_raw="Test",
            keyword_tags=["cta", "price"],
            product_tags=["skincare", "makeup"],
            product_entities=["세럼", "립스틱"],
        )
        request = self._make_request(library_id=lib_id, scenes=[scene])

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            await service.ingest_scenes(request, org_id)

        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = call_args[0]
        assert doc["keyword_tags"] == ["cta", "price"]
        assert doc["product_tags"] == ["skincare", "makeup"]
        assert doc["product_entities"] == ["세럼", "립스틱"]

    @pytest.mark.asyncio
    async def test_ingest_tags_default_empty_when_omitted(
        self, service, mock_db_session, mock_scene_client
    ):
        """Scenes without tags should have empty lists in the indexed doc."""
        org_id = uuid4()
        lib_id = uuid4()

        scene = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            transcript_raw="No tags here",
        )
        request = self._make_request(library_id=lib_id, scenes=[scene])

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            await service.ingest_scenes(request, org_id)

        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = call_args[0]
        assert doc["keyword_tags"] == []
        assert doc["product_tags"] == []
        assert doc["product_entities"] == []

    @pytest.mark.asyncio
    async def test_ingest_source_type_passthrough(
        self, service, mock_db_session, mock_scene_client
    ):
        """source_type and required_drive_nickname should be indexed."""
        org_id = uuid4()
        lib_id = uuid4()

        scene = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            source_type="removable_disk",
            required_drive_nickname="USB-cam-1",
        )
        request = self._make_request(library_id=lib_id, scenes=[scene])

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        await service.ingest_scenes(request, org_id)

        call_args = mock_scene_client.bulk_index_scenes.call_args[0][0]
        _, doc = call_args[0]
        assert doc["source_type"] == "removable_disk"
        assert doc["required_drive_nickname"] == "USB-cam-1"

    @pytest.mark.asyncio
    async def test_ingest_idempotent_double_ingest(
        self, service, mock_db_session, mock_scene_client
    ):
        """Ingesting the same payload twice should produce the same doc_ids (upsert behavior)."""
        org_id = uuid4()
        lib_id = uuid4()

        scenes = [
            IngestSceneDocument(
                scene_id="vid_scene_0",
                index=0,
                start_ms=0,
                end_ms=5000,
                transcript_raw="Test transcript",
            ),
            IngestSceneDocument(
                scene_id="vid_scene_1",
                index=1,
                start_ms=5000,
                end_ms=10000,
                transcript_raw="Another transcript",
            ),
        ]
        request = self._make_request(library_id=lib_id, scenes=scenes)

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_embeddings = [[0.1] * 1024 for _ in range(2)]

        # First ingest
        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=mock_embeddings,
        ):
            result1 = await service.ingest_scenes(request, org_id)

        first_call_docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        first_doc_ids = [doc_id for doc_id, _ in first_call_docs]

        # Second ingest (same payload)
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result2)

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=mock_embeddings,
        ):
            result2 = await service.ingest_scenes(request, org_id)

        second_call_docs = mock_scene_client.bulk_index_scenes.call_args[0][0]
        second_doc_ids = [doc_id for doc_id, _ in second_call_docs]

        # Doc IDs must be identical across both ingests (deterministic composite key)
        assert first_doc_ids == second_doc_ids
        assert result1["indexed_count"] == result2["indexed_count"]
        # Both use "{org_id}:{scene_id}" format
        for doc_id in first_doc_ids:
            assert doc_id.startswith(f"{org_id}:")

    @pytest.mark.asyncio
    async def test_ingest_normalizes_only_once_per_scene(
        self, service, mock_db_session, mock_scene_client
    ):
        """normalize_transcript should be called once per scene (not twice)."""
        org_id = uuid4()
        lib_id = uuid4()
        request = self._make_request(library_id=lib_id)

        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_lib
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.ingest.service.get_passage_embeddings_batch",
            return_value=[[0.1] * 1024],
        ), patch(
            "app.modules.ingest.service.normalize_transcript",
            wraps=lambda x: x.strip().lower(),
        ) as mock_normalize:
            await service.ingest_scenes(request, org_id)

        # Should be called exactly once per scene (1 scene in the request)
        assert mock_normalize.call_count == 1


# ---------------------------------------------------------------------------
# Schema hardening tests (transcript cap, scene_id format)
# ---------------------------------------------------------------------------
class TestSchemaHardening:
    def test_transcript_raw_exceeds_max_length_rejected(self):
        """transcript_raw over 50k chars should be rejected by schema."""
        long_text = "x" * 50_001
        with pytest.raises(Exception):
            IngestSceneDocument(
                scene_id="vid_scene_0",
                index=0,
                start_ms=0,
                end_ms=5000,
                transcript_raw=long_text,
            )

    def test_transcript_raw_at_max_length_accepted(self):
        """transcript_raw exactly 50k chars should be accepted."""
        text = "x" * 50_000
        doc = IngestSceneDocument(
            scene_id="vid_scene_0",
            index=0,
            start_ms=0,
            end_ms=5000,
            transcript_raw=text,
        )
        assert len(doc.transcript_raw) == 50_000

    def test_scene_id_valid_formats(self):
        """Valid scene_id patterns should be accepted."""
        valid_ids = [
            "vid123_scene_0",
            "abc-def_scene_99",
            "some_video_id_scene_123",
            "a_scene_0",
        ]
        for sid in valid_ids:
            doc = IngestSceneDocument(
                scene_id=sid,
                index=0,
                start_ms=0,
                end_ms=1000,
            )
            assert doc.scene_id == sid

    def test_scene_id_invalid_formats_rejected(self):
        """Invalid scene_id patterns should be rejected."""
        invalid_ids = [
            "no_scene_prefix",
            "scene_0",  # missing video_id prefix
            "_scene_0",  # video_id part is empty after split but regex requires .+
            "vid_scene_",  # missing index digits
            "vid_scene_abc",  # index must be digits
        ]
        for sid in invalid_ids:
            with pytest.raises(Exception, match="scene_id"):
                IngestSceneDocument(
                    scene_id=sid,
                    index=0,
                    start_ms=0,
                    end_ms=1000,
                )


# ---------------------------------------------------------------------------
# Correlation header tests (GAP 3)
# ---------------------------------------------------------------------------
class TestCorrelationHeaders:
    """Verify that correlation headers (X-Heimdex-Request-Id, X-Heimdex-Device-Id)
    are optional and do not affect the ingest result."""

    def _make_request(self, library_id=None):
        return IngestScenesRequest(
            video_id="vid_abc",
            library_id=library_id or uuid4(),
            pipeline_version="1.0",
            model_version="whisper-v3",
            total_duration_ms=30000,
            scenes=[
                IngestSceneDocument(
                    scene_id="vid_abc_scene_0",
                    index=0,
                    start_ms=0,
                    end_ms=10000,
                    transcript_raw="test transcript",
                    speech_segment_count=1,
                ),
            ],
        )

    @staticmethod
    def _mock_http_request(headers: dict | None = None):
        """Build a mock starlette Request with optional headers."""
        mock_req = MagicMock()
        header_map = headers or {}
        mock_req.headers = header_map
        return mock_req

    @pytest.mark.asyncio
    async def test_ingest_with_correlation_headers(self):
        """Router should accept and log correlation headers without error."""
        from app.modules.ingest.router import ingest_scenes

        org_ctx = MagicMock()
        org_ctx.org_id = uuid4()
        org_ctx.org_slug = "testorg"

        lib_id = uuid4()
        request = self._make_request(library_id=lib_id)

        mock_service = AsyncMock()
        mock_service.ingest_scenes = AsyncMock(
            return_value={
                "indexed_count": 1,
                "video_id": "vid_abc",
                "skipped_count": 0,
            }
        )

        http_request = self._mock_http_request(
            {
                "x-heimdex-request-id": "req-12345",
                "x-heimdex-device-id": "device-abc",
            }
        )

        with patch("app.modules.ingest.router.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_max_scenes = 500
            result = await ingest_scenes(
                request=request,
                http_request=http_request,
                org_ctx=org_ctx,
                ingest_service=mock_service,
            )

        assert result.indexed_count == 1
        assert result.video_id == "vid_abc"

    @pytest.mark.asyncio
    async def test_ingest_without_correlation_headers(self):
        """Router should work identically when no correlation headers are present."""
        from app.modules.ingest.router import ingest_scenes

        org_ctx = MagicMock()
        org_ctx.org_id = uuid4()
        org_ctx.org_slug = "testorg"

        lib_id = uuid4()
        request = self._make_request(library_id=lib_id)

        mock_service = AsyncMock()
        mock_service.ingest_scenes = AsyncMock(
            return_value={
                "indexed_count": 1,
                "video_id": "vid_abc",
                "skipped_count": 0,
            }
        )

        http_request = self._mock_http_request({})

        with patch("app.modules.ingest.router.get_settings") as mock_settings:
            mock_settings.return_value.agent_ingest_max_scenes = 500
            result = await ingest_scenes(
                request=request,
                http_request=http_request,
                org_ctx=org_ctx,
                ingest_service=mock_service,
            )

        assert result.indexed_count == 1
        assert result.video_id == "vid_abc"
