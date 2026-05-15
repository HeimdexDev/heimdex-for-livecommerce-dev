# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportAny=false, reportUnusedCallResult=false, reportUnknownVariableType=false, reportUnknownMemberType=false

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_scene_client():
    with patch("app.modules.search.scene_client.get_settings") as mock_settings, patch(
        "app.modules.search.scene_client.get_opensearch_client"
    ) as mock_get_client:
        settings = MagicMock()
        settings.opensearch_url = "http://localhost:9200"
        settings.opensearch_index_prefix = "test"
        settings.opensearch_facet_size = 100
        settings.search_rrf_k = 60
        settings.ocr_search_enabled = True
        settings.ocr_bm25_boost = 0.6
        mock_settings.return_value = settings

        async_client = MagicMock()
        async_client.indices = MagicMock()
        async_client.close = AsyncMock()
        async_client.search = AsyncMock(return_value={"hits": {"hits": []}})
        mock_get_client.return_value = async_client

        from app.modules.search.scene_client import SceneSearchClient

        client = SceneSearchClient()
        client.client = async_client
        yield client, async_client


def _extract_should_field_names(body: dict) -> list[str]:
    fields = []
    query = body.get("query", {}).get("bool", {})
    for clause in query.get("should", []):
        for match_type in ("match", "match_phrase"):
            if match_type in clause:
                fields.extend(clause[match_type].keys())
    return fields


def _extract_all_field_names(body: dict) -> list[str]:
    fields = []
    query = body.get("query", {}).get("bool", {})
    for clause in query.get("should", []):
        for match_type in ("match", "match_phrase"):
            if match_type in clause:
                fields.extend(clause[match_type].keys())
    for clause in query.get("must", []):
        for match_type in ("match", "match_phrase"):
            if match_type in clause:
                fields.extend(clause[match_type].keys())
    return fields


class TestLexicalImageSearch:
    @pytest.mark.asyncio
    async def test_filename_text_included_for_image_content_type(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" in fields

    @pytest.mark.asyncio
    async def test_filename_text_included_for_mixed_content_types(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["video", "image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" in fields

    @pytest.mark.asyncio
    async def test_filename_text_excluded_for_video_only(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["video"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" not in fields

    @pytest.mark.asyncio
    async def test_filename_text_excluded_when_no_content_types(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="상품",
            org_id="org-1",
            filters={},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" not in fields

    @pytest.mark.asyncio
    async def test_filename_text_boost_value(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        should = call_body["query"]["bool"]["should"]

        filename_clauses = [
            c for c in should
            if any("filename_text" in c.get(mt, {}) for mt in ("match", "match_phrase"))
        ]
        assert len(filename_clauses) == 2

        match_clause = next(c for c in filename_clauses if "match" in c)
        assert match_clause["match"]["filename_text"]["boost"] == 2.0

        phrase_clause = next(c for c in filename_clauses if "match_phrase" in c)
        assert phrase_clause["match_phrase"]["filename_text"]["boost"] == 4.0

    @pytest.mark.asyncio
    async def test_long_query_includes_filename_text_for_images(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="긴 검색어 테스트 쿼리",
            org_id="org-1",
            filters={"content_types": ["image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_all_field_names(call_body)
        assert "filename_text" in fields

    @pytest.mark.asyncio
    async def test_long_query_excludes_filename_text_for_video(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="긴 검색어 테스트 쿼리",
            org_id="org-1",
            filters={"content_types": ["video"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_all_field_names(call_body)
        assert "filename_text" not in fields


class TestMetadataImageSearch:
    @pytest.mark.asyncio
    async def test_filename_text_included_for_image(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_metadata(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" in fields

    @pytest.mark.asyncio
    async def test_filename_text_excluded_for_video(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_metadata(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["video"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" not in fields

    @pytest.mark.asyncio
    async def test_long_query_includes_filename_text_for_images(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_metadata(
            query="긴 검색어 테스트 쿼리",
            org_id="org-1",
            filters={"content_types": ["image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_all_field_names(call_body)
        assert "filename_text" in fields

    @pytest.mark.asyncio
    async def test_long_query_excludes_filename_text_for_video(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_metadata(
            query="긴 검색어 테스트 쿼리",
            org_id="org-1",
            filters={"content_types": ["video"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_all_field_names(call_body)
        assert "filename_text" not in fields

    @pytest.mark.asyncio
    async def test_metadata_short_query_filename_boost_values(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_metadata(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        should = call_body["query"]["bool"]["should"]

        filename_clauses = [
            c for c in should
            if any("filename_text" in c.get(mt, {}) for mt in ("match", "match_phrase"))
        ]
        assert len(filename_clauses) == 2

        match_clause = next(c for c in filename_clauses if "match" in c)
        assert match_clause["match"]["filename_text"]["boost"] == 2.0

        phrase_clause = next(c for c in filename_clauses if "match_phrase" in c)
        assert phrase_clause["match_phrase"]["filename_text"]["boost"] == 4.0


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_default_filters_no_filename_text_in_lexical(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="테스트",
            org_id="org-1",
            filters={"content_types": ["video"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" not in fields
        assert "transcript_norm" in fields

    @pytest.mark.asyncio
    async def test_default_filters_no_filename_text_in_metadata(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_metadata(
            query="테스트",
            org_id="org-1",
            filters={"content_types": ["video"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "filename_text" not in fields
        assert "video_title.nori" in fields

    @pytest.mark.asyncio
    async def test_existing_fields_preserved_when_images_added(self, mock_scene_client):
        client, mock_async = mock_scene_client

        await client.search_lexical(
            query="상품",
            org_id="org-1",
            filters={"content_types": ["video", "image"]},
        )

        call_body = mock_async.search.call_args.kwargs["body"]
        fields = _extract_should_field_names(call_body)
        assert "transcript_norm" in fields
        assert "video_title.nori" in fields
        assert "scene_caption" in fields
        assert "filename_text" in fields
