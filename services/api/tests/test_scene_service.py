"""
Unit tests for SceneSearchService.

Tests verify:
1. End-to-end search pipeline (lexical + vector -> RRF -> diversification -> results)
2. Alpha blending extremes (pure lexical, pure vector, balanced)
3. Result construction (SceneResult fields, snippet truncation)
4. Facet enrichment with library names and people labels
5. Empty results handling
6. Filter passthrough to SceneSearchClient

Run with: pytest tests/test_scene_service.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.modules.search.schemas import SceneSearchResponse, SearchFilters, SearchRequest
from app.modules.search.scene_service import SceneSearchService


def _make_scene_hit(
    scene_id: str,
    video_id: str,
    score: float = 10.0,
    library_id: str | None = None,
    transcript: str = "Test transcript content for scene",
    ocr_text_raw: str = "",
    ocr_char_count: int = 0,
    source_type: str = "gdrive",
    speech_segment_count: int = 3,
) -> dict[str, object]:
    """Helper to construct an OpenSearch scene hit dict."""
    return {
        "_id": scene_id,
        "_score": score,
        "_source": {
            "scene_id": scene_id,
            "video_id": video_id,
            "library_id": library_id or str(uuid4()),
            "start_ms": 0,
            "end_ms": 5000,
            "transcript_raw": transcript,
            "ocr_text_raw": ocr_text_raw,
            "ocr_char_count": ocr_char_count,
            "source_type": source_type,
            "people_cluster_ids": [],
            "speech_segment_count": speech_segment_count,
            "transcript_char_count": len(transcript),
        },
    }


class TestSceneSearchService:
    @pytest.fixture
    def scene_search_service(self, mock_db_session, mock_scene_opensearch_client):
        return SceneSearchService(mock_db_session, mock_scene_opensearch_client)

    @pytest.fixture
    def _patch_db_session(self, scene_search_service):
        """Patch session.execute to return empty library/people results."""
        with patch.object(scene_search_service.session, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_execute.return_value = mock_result
            yield mock_execute

    # ------------------------------------------------------------------
    # Basic search pipeline
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_returns_scene_search_response(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """search() should return a SceneSearchResponse."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene1", "vid1"),
        ]
        mock_scene_opensearch_client.search_vector.return_value = []

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert isinstance(response, SceneSearchResponse)
        assert response.query == "test"
        assert response.alpha == 0.5
        assert response.result_type == "scene"
        assert response.total_candidates >= 1
        assert len(response.results) >= 1

    @pytest.mark.asyncio
    async def test_search_result_has_scene_fields(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Each SceneResult should have scene-specific fields."""
        org_id = uuid4()
        lib_id = str(uuid4())

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene_001", "vid_abc", library_id=lib_id,
                            transcript="Hello scene", speech_segment_count=5),
        ]

        response = await scene_search_service.search(
            query="hello", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        r = response.results[0]
        assert r.scene_id == "scene_001"
        assert r.video_id == "vid_abc"
        assert r.start_ms == 0
        assert r.end_ms == 5000
        assert r.snippet == "Hello scene"
        assert r.source_type == "gdrive"
        assert r.speech_segment_count == 5
        assert r.debug.fused_score > 0

    # ------------------------------------------------------------------
    # Mode-specific search behavior
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_lexical_mode_only_runs_lexical(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Lexical mode should only call search_lexical, not search_vector."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("lex_scene", "v1", score=10.0),
        ]
        mock_scene_opensearch_client.search_vector.return_value = [
            _make_scene_hit("vec_scene", "v2", score=0.95),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.0, filters=SearchFilters(),
            search_mode="lexical",
        )

        # Lexical mode: only lexical results returned
        assert len(response.results) == 1
        assert response.results[0].scene_id == "lex_scene"
        mock_scene_opensearch_client.search_vector.assert_not_called()

    @pytest.mark.asyncio
    async def test_semantic_mode_runs_rrf_fusion(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Semantic mode should fuse lexical + vector results via 3-way RRF."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("lex_scene", "v1", score=10.0),
        ]
        mock_scene_opensearch_client.search_vector.return_value = [
            _make_scene_hit("vec_scene", "v2", score=0.95),
        ]
        mock_scene_opensearch_client.search_visual_vector = AsyncMock(return_value=[])

        with patch("app.modules.search.scene_service.get_query_embedding", new_callable=AsyncMock) as mock_embed, \
             patch("app.modules.search.scene_service.get_visual_query_embedding", new_callable=AsyncMock) as mock_vis_embed:
            mock_embed.return_value = [0.1] * 1024
            mock_vis_embed.return_value = [0.1] * 768
            response = await scene_search_service.search(
                query="test", org_id=org_id, alpha=1.0, filters=SearchFilters(),
                search_mode="semantic",
            )

        # Semantic mode fuses both lexical and vector via RRF
        assert len(response.results) == 2
        scene_ids = {r.scene_id for r in response.results}
        assert "lex_scene" in scene_ids
        assert "vec_scene" in scene_ids
        # Both lexical and vector should be called
        mock_scene_opensearch_client.search_lexical.assert_called_once()
        mock_scene_opensearch_client.search_vector.assert_called_once()
    @pytest.mark.asyncio
    async def test_default_mode_is_lexical(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Default search_mode should be lexical for backward compatibility."""
        org_id = uuid4()

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("lex_scene", "v1", score=8.0),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
            # no search_mode → defaults to lexical
        )

        assert len(response.results) == 1
        r = response.results[0]
        assert r.debug.lexical_rank is not None
        # Vector contributions should be zero in lexical mode
        assert r.debug.vector_rank is None
        assert r.debug.vector_contribution == 0.0
    # ------------------------------------------------------------------
    # Diversification
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_diversification_limits_per_video(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Diversification should limit scenes from the same video."""
        org_id = uuid4()

        # 10 scenes from same video
        lexical_hits = [
            _make_scene_hit(f"scene_{i}", "same_video", score=10.0 - i)
            for i in range(10)
        ]
        mock_scene_opensearch_client.search_lexical.return_value = lexical_hits
        mock_scene_opensearch_client.search_vector.return_value = []

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.0, filters=SearchFilters()
        )

        # All from same video, but diversification applied
        assert response.total_candidates == 10
        assert len(response.results) <= 20  # page_size cap

    # ------------------------------------------------------------------
    # Snippet truncation
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_snippet_truncated_to_500_chars(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Snippet should be truncated to 500 characters max."""
        org_id = uuid4()
        long_transcript = "A" * 1000

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene_long", "v1", transcript=long_transcript),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert len(response.results[0].snippet) == 500

    @pytest.mark.asyncio
    async def test_result_includes_ocr_snippet_and_ocr_char_count(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        org_id = uuid4()
        raw_ocr = "<b>SALE</b> " + ("X" * 250)

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit(
                "scene_ocr",
                "v1",
                transcript="short",
                ocr_text_raw=raw_ocr,
                ocr_char_count=128,
            ),
        ]

        response = await scene_search_service.search(
            query="sale", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        result = response.results[0]
        assert result.ocr_char_count == 128
        assert len(result.ocr_snippet) <= 212
        assert "&lt;b&gt;SALE&lt;/b&gt;" in result.ocr_snippet
        assert result.debug.ocr_contribution == 0.0

    # ------------------------------------------------------------------
    # Facets
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_facets_returned(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Facets should be populated from SceneSearchClient aggregations."""
        org_id = uuid4()

        mock_scene_opensearch_client.get_facets.return_value = {
            "libraries": [{"key": "lib1", "doc_count": 5}],
            "source_types": [{"key": "gdrive", "doc_count": 10}],
            "people": [{"key": "cluster_001", "doc_count": 3}],
        }

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert len(response.facets.libraries) == 1
        assert response.facets.libraries[0].value == "lib1"
        assert response.facets.libraries[0].count == 5
        assert len(response.facets.source_types) == 1
        assert len(response.facets.people_cluster_ids) == 1

    # ------------------------------------------------------------------
    # Empty results
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_empty_results(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Search with no matches should return empty results list."""
        org_id = uuid4()

        response = await scene_search_service.search(
            query="nonexistent", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        assert isinstance(response, SceneSearchResponse)
        assert response.results == []
        assert response.total_candidates == 0
        assert response.result_type == "scene"

    # ------------------------------------------------------------------
    # Filter passthrough
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_filters_passed_to_client(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        """Filters should be forwarded to SceneSearchClient methods."""
        org_id = uuid4()
        lib_id = uuid4()

        mock_lib = MagicMock()
        mock_lib.id = str(lib_id)
        mock_lib.name = "Test Library"

        filters = SearchFilters(
            source_types=["gdrive"],
            library_ids=[lib_id],
            person_cluster_ids=["cluster1"],
        )

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = []
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.side_effect = [people_result, lib_result]

            await scene_search_service.search(
                query="test", org_id=org_id, alpha=0.5, filters=filters
            )

        call_args = mock_scene_opensearch_client.search_lexical.call_args
        filter_dict = call_args.kwargs["filters"]
        assert filter_dict["source_types"] == ["gdrive"]
        assert filter_dict["library_ids"] == [lib_id]
        assert filter_dict["person_cluster_ids"] == ["cluster1"]

    @pytest.mark.asyncio
    async def test_include_ocr_passed_to_client(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        org_id = uuid4()

        await scene_search_service.search(
            query="test",
            org_id=org_id,
            alpha=0.5,
            filters=SearchFilters(),
            include_ocr=False,
        )

        call_args = mock_scene_opensearch_client.search_lexical.call_args
        assert call_args.kwargs["include_ocr"] is False

    # ------------------------------------------------------------------
    # Tag filter passthrough (PR-D)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_tag_filters_passed_to_client(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Tag filter fields should be forwarded to SceneSearchClient."""
        org_id = uuid4()

        filters = SearchFilters(
            keyword_tags_in=["할인"],
            keyword_tags_not_in=["광고"],
            product_tags_in=["cosmetics"],
            product_tags_not_in=["alcohol"],
            product_entities_in=["Nike Air Max"],
            product_entities_not_in=["BadBrand"],
        )

        await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=filters
        )

        call_args = mock_scene_opensearch_client.search_lexical.call_args
        fd = call_args.kwargs["filters"]
        assert fd["keyword_tags_in"] == ["할인"]
        assert fd["keyword_tags_not_in"] == ["광고"]
        assert fd["product_tags_in"] == ["cosmetics"]
        assert fd["product_tags_not_in"] == ["alcohol"]
        assert fd["product_entities_in"] == ["Nike Air Max"]
        assert fd["product_entities_not_in"] == ["BadBrand"]

    @pytest.mark.asyncio
    async def test_empty_tag_filters_passed_as_empty_lists(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Default (empty) tag filters should appear as empty lists in filter_dict."""
        org_id = uuid4()

        await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        call_args = mock_scene_opensearch_client.search_lexical.call_args
        fd = call_args.kwargs["filters"]
        assert fd["keyword_tags_in"] == []
        assert fd["keyword_tags_not_in"] == []
        assert fd["product_tags_in"] == []
        assert fd["product_tags_not_in"] == []
        assert fd["product_entities_in"] == []
        assert fd["product_entities_not_in"] == []

    # ------------------------------------------------------------------
    # Library name enrichment
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_library_name_enrichment(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        """Results should have library_name populated from DB lookup."""
        org_id = uuid4()
        lib_id = str(uuid4())

        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("scene1", "v1", library_id=lib_id),
        ]

        # Mock library lookup to return a library with matching id
        mock_lib = MagicMock()
        mock_lib.id = lib_id
        mock_lib.name = "My Library"

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = []
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.side_effect = [people_result, lib_result]

            response = await scene_search_service.search(
                query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
            )

        assert response.results[0].library_name == "My Library"

    # ------------------------------------------------------------------
    # Person name detection in query
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_person_name_in_query_adds_cluster_filter(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        org_id = uuid4()

        mock_person = MagicMock()
        mock_person.person_cluster_id = "cluster_abc"
        mock_person.label = "장원영"

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = [mock_person]
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = []
            mock_execute.side_effect = [people_result, lib_result]

            await scene_search_service.search(
                query="장원영", org_id=org_id, alpha=0.5, filters=SearchFilters()
            )

        filter_dict = mock_scene_opensearch_client.search_lexical.call_args.kwargs["filters"]
        assert filter_dict["person_cluster_ids"] == ["cluster_abc"]

        matched = mock_scene_opensearch_client.search_lexical.call_args.kwargs["matched_person_cluster_ids"]
        assert matched == ["cluster_abc"]

    @pytest.mark.asyncio
    async def test_person_name_merged_with_explicit_filter(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        org_id = uuid4()

        mock_person = MagicMock()
        mock_person.person_cluster_id = "cluster_abc"
        mock_person.label = "장원영"

        filters = SearchFilters(person_cluster_ids=["cluster_xyz"])

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = [mock_person]
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = []
            mock_execute.side_effect = [people_result, lib_result]

            await scene_search_service.search(
                query="장원영", org_id=org_id, alpha=0.5, filters=filters
            )

        filter_dict = mock_scene_opensearch_client.search_lexical.call_args.kwargs["filters"]
        assert set(filter_dict["person_cluster_ids"]) == {"cluster_abc", "cluster_xyz"}

    @pytest.mark.asyncio
    async def test_no_person_match_leaves_filter_unchanged(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        org_id = uuid4()

        await scene_search_service.search(
            query="화장품 추천", org_id=org_id, alpha=0.5, filters=SearchFilters()
        )

        filter_dict = mock_scene_opensearch_client.search_lexical.call_args.kwargs["filters"]
        assert filter_dict["person_cluster_ids"] is None

        matched = mock_scene_opensearch_client.search_lexical.call_args.kwargs["matched_person_cluster_ids"]
        assert matched is None

    @pytest.mark.asyncio
    async def test_person_name_overrides_global_exclusion(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        org_id = uuid4()
        user_id = uuid4()

        mock_person = MagicMock()
        mock_person.person_cluster_id = "cluster_abc"
        mock_person.label = "장원영"

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = [mock_person]

            exclude_result = MagicMock()
            exclude_result.scalars.return_value.all.return_value = [
                "cluster_abc", "cluster_other"
            ]

            video_excl_result = MagicMock()
            video_excl_result.tuples.return_value.all.return_value = []

            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = []

            mock_execute.side_effect = [
                people_result,
                exclude_result,
                video_excl_result,
                lib_result,
            ]

            await scene_search_service.search(
                query="장원영",
                org_id=org_id,
                alpha=0.5,
                filters=SearchFilters(),
                user_id=user_id,
            )

        filter_dict = mock_scene_opensearch_client.search_lexical.call_args.kwargs["filters"]
        assert filter_dict["person_cluster_ids"] == ["cluster_abc"]
        assert filter_dict["person_cluster_ids_not_in"] == ["cluster_other"]

    # ------------------------------------------------------------------
    # Quality factor applied (via shared fusion logic)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_quality_factor_applied(
        self, scene_search_service, mock_scene_opensearch_client, _patch_db_session
    ):
        """Quality factor from transcript length should affect adjusted_score."""
        org_id = uuid4()

        # Short transcript -> quality penalty
        mock_scene_opensearch_client.search_lexical.return_value = [
            _make_scene_hit("short_scene", "v1", transcript="Hi"),
        ]

        response = await scene_search_service.search(
            query="test", org_id=org_id, alpha=0.0, filters=SearchFilters()
        )

        r = response.results[0]
        assert r.debug.quality_factor < 1.0
        assert r.debug.adjusted_score < r.debug.fused_score


class TestLibraryIdValidation:
    """Validate that library_ids in search filters belong to the requesting org."""

    @pytest.fixture
    def scene_search_service(self, mock_db_session, mock_scene_opensearch_client):
        return SceneSearchService(mock_db_session, mock_scene_opensearch_client)

    @pytest.mark.asyncio
    async def test_unknown_library_id_returns_400(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        """library_ids not belonging to the org should be rejected with 400."""
        from fastapi import HTTPException

        org_id = uuid4()
        known_lib_id = uuid4()
        unknown_lib_id = uuid4()

        mock_lib = MagicMock()
        mock_lib.id = str(known_lib_id)
        mock_lib.name = "Known Library"

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = []
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.side_effect = [people_result, lib_result]

            filters = SearchFilters(library_ids=[unknown_lib_id])
            with pytest.raises(HTTPException) as exc_info:
                await scene_search_service.search(
                    query="test", org_id=org_id, alpha=0.5, filters=filters
                )
            assert exc_info.value.status_code == 400
            assert "Unknown library_ids" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_known_library_id_passes(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        """library_ids belonging to the org should pass validation."""
        org_id = uuid4()
        lib_id = uuid4()

        mock_lib = MagicMock()
        mock_lib.id = str(lib_id)
        mock_lib.name = "My Library"

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = []
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.side_effect = [people_result, lib_result]

            filters = SearchFilters(library_ids=[lib_id])
            response = await scene_search_service.search(
                query="test", org_id=org_id, alpha=0.5, filters=filters
            )
            assert response is not None

    @pytest.mark.asyncio
    async def test_no_library_ids_skips_validation(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        """When no library_ids are specified, validation is skipped."""
        org_id = uuid4()

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_execute.return_value = mock_result

            response = await scene_search_service.search(
                query="test", org_id=org_id, alpha=0.5, filters=SearchFilters()
            )
            assert response is not None

    @pytest.mark.asyncio
    async def test_mixed_known_unknown_returns_400(
        self, scene_search_service, mock_scene_opensearch_client
    ):
        """Mix of known and unknown library_ids should be rejected."""
        from fastapi import HTTPException

        org_id = uuid4()
        known_id = uuid4()
        unknown_id = uuid4()

        mock_lib = MagicMock()
        mock_lib.id = str(known_id)
        mock_lib.name = "Known"

        with patch.object(scene_search_service.session, "execute") as mock_execute:
            people_result = MagicMock()
            people_result.scalars.return_value.all.return_value = []
            lib_result = MagicMock()
            lib_result.scalars.return_value.all.return_value = [mock_lib]
            mock_execute.side_effect = [people_result, lib_result]

            filters = SearchFilters(library_ids=[known_id, unknown_id])
            with pytest.raises(HTTPException) as exc_info:
                await scene_search_service.search(
                    query="test", org_id=org_id, alpha=0.5, filters=filters
                )
            assert exc_info.value.status_code == 400


def test_search_request_include_ocr_default_none():
    req = SearchRequest(q="test")
    assert req.include_ocr is None


def test_search_request_include_ocr_explicit():
    req = SearchRequest(q="test", include_ocr=False)
    assert req.include_ocr is False
