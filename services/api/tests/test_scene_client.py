"""
Unit tests for SceneSearchClient.

Tests verify:
1. Index creation with correct mapping (scene fields, Nori, kNN)
2. Alias creation and mismatch detection
3. Single and bulk scene indexing
4. Lexical search (BM25) and vector search (kNN)
5. Idempotent index creation
6. Alias promotion (atomic swap)
7. Filter clause construction

Run with: pytest tests/test_scene_client.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSceneSearchClient:
    """Unit tests for SceneSearchClient using mocks (no live OpenSearch)."""

    @pytest.fixture
    def mock_scene_client(self):
        """Create a mocked SceneSearchClient with controllable behavior."""
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client") as mock_get_client:

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test_scenes"
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()
            mock_get_client.return_value = async_client

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    # ------------------------------------------------------------------
    # Index naming
    # ------------------------------------------------------------------
    def test_index_naming_convention(self, mock_scene_client):
        """Index names follow {prefix}_scenes / {prefix}_scenes_{version} pattern."""
        client, _ = mock_scene_client
        assert client.alias_name == "test_scenes_scenes"
        assert client.index_name == "test_scenes_scenes_v1"
        assert client.EMBEDDING_DIMENSION == 1024

    # ------------------------------------------------------------------
    # Index creation
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_index_with_nori(self, mock_scene_client):
        """create_index should include Nori analyzer when available."""
        client, mock_async = mock_scene_client

        # Nori available
        mock_async.cat.plugins = AsyncMock(
            return_value=[{"component": "analysis-nori"}]
        )
        mock_async.indices.create = AsyncMock()

        await client.create_index()

        mock_async.indices.create.assert_called_once()
        call_body = mock_async.indices.create.call_args.kwargs["body"]

        # Verify Nori analyzer is configured
        analysis = call_body["settings"]["analysis"]
        assert "korean_tokenizer" in analysis["tokenizer"]
        assert "korean_pos_filter" in analysis["filter"]
        assert "korean_analyzer" in analysis["analyzer"]

        # Verify transcript_norm uses korean_analyzer
        props = call_body["mappings"]["properties"]
        assert props["transcript_norm"]["analyzer"] == "korean_analyzer"

    @pytest.mark.asyncio
    async def test_create_index_without_nori(self, mock_scene_client):
        """create_index should use fallback analyzer when Nori unavailable."""
        client, mock_async = mock_scene_client

        # Nori NOT available
        mock_async.cat.plugins = AsyncMock(return_value=[])
        mock_async.indices.create = AsyncMock()

        await client.create_index()

        call_body = mock_async.indices.create.call_args.kwargs["body"]
        analysis = call_body["settings"]["analysis"]

        # No Nori tokenizer
        assert analysis["tokenizer"] == {}
        assert analysis["filter"] == {}

        # Fallback analyzer only
        assert "fallback_analyzer" in analysis["analyzer"]
        assert "korean_analyzer" not in analysis["analyzer"]

        # transcript_norm uses fallback
        props = call_body["mappings"]["properties"]
        assert props["transcript_norm"]["analyzer"] == "fallback_analyzer"

    @pytest.mark.asyncio
    async def test_create_index_mapping_has_scene_fields(self, mock_scene_client):
        """Index mapping should contain all scene-specific fields."""
        client, mock_async = mock_scene_client

        mock_async.cat.plugins = AsyncMock(return_value=[])
        mock_async.indices.create = AsyncMock()

        await client.create_index()

        call_body = mock_async.indices.create.call_args.kwargs["body"]
        props = call_body["mappings"]["properties"]

        # Core scene fields
        assert props["scene_id"]["type"] == "keyword"
        assert props["video_id"]["type"] == "keyword"
        assert props["video_title"]["type"] == "keyword"
        assert props["org_id"]["type"] == "keyword"
        assert props["library_id"]["type"] == "keyword"
        assert props["start_ms"]["type"] == "integer"
        assert props["end_ms"]["type"] == "integer"
        assert props["transcript_raw"]["type"] == "text"
        assert props["transcript_norm"]["type"] == "text"
        assert props["transcript_char_count"]["type"] == "integer"
        assert props["speech_segment_count"]["type"] == "integer"

        # kNN vector
        emb = props["embedding_vector"]
        assert emb["type"] == "knn_vector"
        assert emb["dimension"] == 1024
        assert emb["method"]["name"] == "hnsw"
        assert emb["method"]["space_type"] == "cosinesimil"
        assert emb["method"]["engine"] == "lucene"
        assert emb["method"]["parameters"]["ef_construction"] == 128
        assert emb["method"]["parameters"]["m"] == 24

        # People + metadata
        assert props["people_cluster_ids"]["type"] == "keyword"
        # Tags
        assert props["keyword_tags"]["type"] == "keyword"
        assert props["product_tags"]["type"] == "keyword"
        assert props["product_entities"]["type"] == "keyword"
        assert props["thumbnail_url"]["type"] == "keyword"
        assert props["thumbnail_url"]["index"] is False
        assert props["source_type"]["type"] == "keyword"
        assert props["capture_time"]["type"] == "date"
        assert props["ingest_time"]["type"] == "date"

    @pytest.mark.asyncio
    async def test_create_index_includes_alias(self, mock_scene_client):
        """create_index should set up alias in single creation call."""
        client, mock_async = mock_scene_client

        mock_async.cat.plugins = AsyncMock(return_value=[])
        mock_async.indices.create = AsyncMock()

        await client.create_index()

        call_body = mock_async.indices.create.call_args.kwargs["body"]
        assert client.alias_name in call_body["aliases"]

    @pytest.mark.asyncio
    async def test_create_index_idempotent(self, mock_scene_client):
        """create_index should handle resource_already_exists gracefully."""
        client, mock_async = mock_scene_client

        mock_async.cat.plugins = AsyncMock(return_value=[])
        mock_async.indices.create = AsyncMock(
            side_effect=Exception("resource_already_exists_exception")
        )

        # Should not raise
        await client.create_index()

    @pytest.mark.asyncio
    async def test_create_index_reraises_other_errors(self, mock_scene_client):
        """create_index should re-raise non-duplicate errors."""
        client, mock_async = mock_scene_client

        mock_async.cat.plugins = AsyncMock(return_value=[])
        mock_async.indices.create = AsyncMock(
            side_effect=Exception("connection_refused")
        )

        with pytest.raises(Exception, match="connection_refused"):
            await client.create_index()

    # ------------------------------------------------------------------
    # ensure_index_exists
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_ensure_index_creates_when_missing(self, mock_scene_client):
        """ensure_index_exists should create index and alias when both missing."""
        client, mock_async = mock_scene_client

        mock_async.indices.exists = AsyncMock(return_value=False)
        mock_async.cat.plugins = AsyncMock(return_value=[])
        mock_async.indices.create = AsyncMock()

        result = await client.ensure_index_exists()

        assert result["index_created"] is True
        assert result["alias_created"] is True
        mock_async.indices.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_index_creates_alias_when_missing(self, mock_scene_client):
        """ensure_index_exists should create alias when index exists but alias missing."""
        client, mock_async = mock_scene_client

        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_alias = AsyncMock(
            side_effect=Exception("alias not found")
        )
        mock_async.indices.put_alias = AsyncMock()

        result = await client.ensure_index_exists()

        assert result["index_created"] is False
        assert result["alias_created"] is True
        mock_async.indices.put_alias.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_index_warns_on_alias_mismatch(self, mock_scene_client):
        """ensure_index_exists should warn but NOT auto-flip on version mismatch."""
        client, mock_async = mock_scene_client

        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_alias = AsyncMock(return_value={
            "test_scenes_scenes_v0": {"aliases": {"test_scenes_scenes": {}}},
        })

        result = await client.ensure_index_exists()

        assert result["alias_mismatch_warning"] is not None
        assert "ALIAS MISMATCH" in result["alias_mismatch_warning"]
        assert result["alias_current_targets"] == ["test_scenes_scenes_v0"]

        # Should NOT have called put_alias (no auto-flip)
        mock_async.indices.put_alias.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_index_noop_when_correct(self, mock_scene_client):
        """ensure_index_exists should be no-op when index and alias are correct."""
        client, mock_async = mock_scene_client

        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_alias = AsyncMock(return_value={
            client.index_name: {"aliases": {client.alias_name: {}}},
        })

        result = await client.ensure_index_exists()

        assert result["index_created"] is False
        assert result["alias_created"] is False
        assert result["alias_mismatch_warning"] is None

    # ------------------------------------------------------------------
    # Alias promotion
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_promote_alias_atomic_swap(self, mock_scene_client):
        """promote_alias_to_current_version should perform atomic swap."""
        client, mock_async = mock_scene_client

        mock_async.indices.exists = AsyncMock(return_value=True)

        alias_state = {"targets": ["test_scenes_scenes_v0"]}

        async def mock_get_alias(*args, **kwargs):
            if alias_state["targets"]:
                return {idx: {"aliases": {}} for idx in alias_state["targets"]}
            raise Exception("alias not found")

        async def mock_update_aliases(body=None):
            alias_state["targets"] = [client.index_name]
            return {"acknowledged": True}

        mock_async.indices.get_alias = mock_get_alias
        mock_async.indices.update_aliases = mock_update_aliases

        result = await client.promote_alias_to_current_version()

        assert result["success"] is True
        assert result["before_targets"] == ["test_scenes_scenes_v0"]
        assert result["after_targets"] == [client.index_name]

    @pytest.mark.asyncio
    async def test_promote_alias_noop_when_current(self, mock_scene_client):
        """promote_alias should be no-op when alias already points to current."""
        client, mock_async = mock_scene_client

        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_alias = AsyncMock(return_value={
            client.index_name: {"aliases": {client.alias_name: {}}},
        })

        result = await client.promote_alias_to_current_version()

        assert result["success"] is True
        assert result["already_current"] is True

    @pytest.mark.asyncio
    async def test_promote_alias_fails_if_index_missing(self, mock_scene_client):
        """promote_alias should fail if target index doesn't exist."""
        client, mock_async = mock_scene_client

        mock_async.indices.exists = AsyncMock(return_value=False)
        mock_async.indices.get_alias = AsyncMock(return_value={})

        with pytest.raises(ValueError, match="does not exist"):
            await client.promote_alias_to_current_version()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_index_single_scene(self, mock_scene_client):
        """index_scene should index a single document."""
        client, mock_async = mock_scene_client

        mock_async.index = AsyncMock()

        doc = {
            "org_id": "org1",
            "scene_id": "vid1_scene_000",
            "video_id": "vid1",
            "start_ms": 0,
            "end_ms": 5000,
            "transcript_raw": "테스트 대본",
        }
        await client.index_scene("vid1_scene_000", doc)

        mock_async.index.assert_called_once_with(
            index=client.index_name,
            id="vid1_scene_000",
            body=doc,
            refresh=True,
        )

    @pytest.mark.asyncio
    async def test_bulk_index_scenes(self, mock_scene_client):
        """bulk_index_scenes should send bulk request."""
        client, mock_async = mock_scene_client

        mock_async.bulk = AsyncMock()

        docs = [
            ("scene1", {"scene_id": "scene1", "transcript_raw": "Hello"}),
            ("scene2", {"scene_id": "scene2", "transcript_raw": "World"}),
        ]
        await client.bulk_index_scenes(docs)

        mock_async.bulk.assert_called_once()
        call_body = mock_async.bulk.call_args.kwargs["body"]

        # 2 documents × 2 actions (index header + doc body) = 4 items
        assert len(call_body) == 4
        assert call_body[0] == {"index": {"_index": client.index_name, "_id": "scene1"}}
        assert call_body[1] == {"scene_id": "scene1", "transcript_raw": "Hello"}

    @pytest.mark.asyncio
    async def test_bulk_index_empty_noop(self, mock_scene_client):
        """bulk_index_scenes with empty list should not call bulk."""
        client, mock_async = mock_scene_client

        mock_async.bulk = AsyncMock()

        await client.bulk_index_scenes([])

        mock_async.bulk.assert_not_called()

    # ------------------------------------------------------------------
    # Lexical search
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_lexical_returns_hits(self, mock_scene_client):
        """search_lexical should query the alias and return hits."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": "scene1",
                        "_score": 10.0,
                        "_source": {
                            "scene_id": "scene1",
                            "video_id": "vid1",
                            "transcript_raw": "검색 결과",
                        },
                    }
                ]
            }
        })

        results = await client.search_lexical("검색", "org1", {})

        assert len(results) == 1
        assert results[0]["_id"] == "scene1"

        # Verify search was against alias
        call_kwargs = mock_async.search.call_args.kwargs
        assert call_kwargs["index"] == client.alias_name

    @pytest.mark.asyncio
    async def test_search_lexical_short_query_phrase_boost(self, mock_scene_client):
        """Short queries (<=3 words) should include phrase boost."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        await client.search_lexical("할인 행사", "org1", {})

        call_body = mock_async.search.call_args.kwargs["body"]
        query = call_body["query"]["bool"]

        # Short query: should have 'should' with match_phrase boost
        assert "should" in query
        phrase_clauses = [c for c in query["should"] if "match_phrase" in c]
        assert len(phrase_clauses) == 1
        assert phrase_clauses[0]["match_phrase"]["transcript_norm"]["boost"] == 2.0

    @pytest.mark.asyncio
    async def test_search_lexical_long_query_no_phrase_boost(self, mock_scene_client):
        """Long queries (>3 words) should not include phrase boost."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        await client.search_lexical("this is a long query string", "org1", {})

        call_body = mock_async.search.call_args.kwargs["body"]
        query = call_body["query"]["bool"]

        # Long query: should have 'must' without phrase boost
        assert "should" not in query
        assert len(query["must"]) == 2  # org_id term + match query

    @pytest.mark.asyncio
    async def test_search_lexical_includes_org_filter(self, mock_scene_client):
        """search_lexical should always filter by org_id."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        await client.search_lexical("test", "my_org", {})

        call_body = mock_async.search.call_args.kwargs["body"]
        query = call_body["query"]["bool"]

        # org_id must be in the query
        org_terms = [c for c in query["must"] if "term" in c and "org_id" in c.get("term", {})]
        assert len(org_terms) == 1
        assert org_terms[0]["term"]["org_id"] == "my_org"

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_vector_returns_hits(self, mock_scene_client):
        """search_vector should query with kNN and return hits."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": "scene2",
                        "_score": 0.95,
                        "_source": {
                            "scene_id": "scene2",
                            "video_id": "vid2",
                            "transcript_raw": "의미 검색",
                        },
                    }
                ]
            }
        })

        embedding = [0.1] * 1024
        results = await client.search_vector(embedding, "org1", {})

        assert len(results) == 1
        assert results[0]["_id"] == "scene2"

        # Verify kNN structure
        call_body = mock_async.search.call_args.kwargs["body"]
        knn = call_body["query"]["knn"]["embedding_vector"]
        assert knn["vector"] == embedding
        assert knn["k"] == 200  # default size

    @pytest.mark.asyncio
    async def test_search_vector_includes_org_filter(self, mock_scene_client):
        """search_vector should always filter by org_id."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        embedding = [0.1] * 1024
        await client.search_vector(embedding, "my_org", {})

        call_body = mock_async.search.call_args.kwargs["body"]
        knn_filter = call_body["query"]["knn"]["embedding_vector"]["filter"]["bool"]["must"]

        org_terms = [c for c in knn_filter if "term" in c and "org_id" in c.get("term", {})]
        assert len(org_terms) == 1
        assert org_terms[0]["term"]["org_id"] == "my_org"

    # ------------------------------------------------------------------
    # Filter clauses
    # ------------------------------------------------------------------
    def test_build_filter_clauses_empty(self, mock_scene_client):
        """Empty filters should return empty clauses tuple."""
        client, _ = mock_scene_client
        clauses, must_not = client._build_filter_clauses({})
        assert clauses == []
        assert must_not == []

    def test_build_filter_clauses_date_range(self, mock_scene_client):
        """Date filters should produce range clause."""
        from datetime import datetime, timezone

        client, _ = mock_scene_client

        date_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
        date_to = datetime(2025, 12, 31, tzinfo=timezone.utc)

        clauses, must_not = client._build_filter_clauses({
            "date_from": date_from,
            "date_to": date_to,
        })

        assert len(clauses) == 1
        assert must_not == []
        range_clause = clauses[0]["range"]["capture_time"]
        assert "gte" in range_clause
        assert "lte" in range_clause

    def test_build_filter_clauses_source_types(self, mock_scene_client):
        """Source type filter should produce terms clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "source_types": ["gdrive", "removable_disk"],
        })

        assert len(clauses) == 1
        assert must_not == []
        assert clauses[0]["terms"]["source_type"] == ["gdrive", "removable_disk"]

    def test_build_filter_clauses_library_ids(self, mock_scene_client):
        """Library ID filter should produce terms clause with stringified UUIDs."""
        from uuid import uuid4

        client, _ = mock_scene_client
        lib_id = uuid4()

        clauses, must_not = client._build_filter_clauses({
            "library_ids": [lib_id],
        })

        assert len(clauses) == 1
        assert must_not == []
        assert clauses[0]["terms"]["library_id"] == [str(lib_id)]

    def test_build_filter_clauses_person_cluster_ids(self, mock_scene_client):
        """Person cluster filter should produce terms clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "person_cluster_ids": ["cluster_001", "cluster_002"],
        })

        assert len(clauses) == 1
        assert must_not == []
        assert clauses[0]["terms"]["people_cluster_ids"] == ["cluster_001", "cluster_002"]

    def test_build_filter_clauses_combined(self, mock_scene_client):
        """Multiple filters should produce multiple clauses."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "source_types": ["gdrive"],
            "person_cluster_ids": ["cluster_001"],
        })

        assert len(clauses) == 2
        assert must_not == []

    # ------------------------------------------------------------------
    # Tag filter clauses (PR-D)
    # ------------------------------------------------------------------
    def test_build_filter_clauses_keyword_tags_in(self, mock_scene_client):
        """keyword_tags_in should produce a terms filter clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "keyword_tags_in": ["할인", "프로모션"],
        })

        assert len(clauses) == 1
        assert must_not == []
        assert clauses[0]["terms"]["keyword_tags"] == ["할인", "프로모션"]

    def test_build_filter_clauses_keyword_tags_not_in(self, mock_scene_client):
        """keyword_tags_not_in should produce a must_not terms clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "keyword_tags_not_in": ["광고"],
        })

        assert clauses == []
        assert len(must_not) == 1
        assert must_not[0]["terms"]["keyword_tags"] == ["광고"]

    def test_build_filter_clauses_product_tags_in(self, mock_scene_client):
        """product_tags_in should produce a terms filter clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "product_tags_in": ["cosmetics", "skincare"],
        })

        assert len(clauses) == 1
        assert clauses[0]["terms"]["product_tags"] == ["cosmetics", "skincare"]

    def test_build_filter_clauses_product_tags_not_in(self, mock_scene_client):
        """product_tags_not_in should produce a must_not terms clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "product_tags_not_in": ["alcohol"],
        })

        assert clauses == []
        assert len(must_not) == 1
        assert must_not[0]["terms"]["product_tags"] == ["alcohol"]

    def test_build_filter_clauses_product_entities_in(self, mock_scene_client):
        """product_entities_in should produce a terms filter clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "product_entities_in": ["Nike Air Max", "Adidas Boost"],
        })

        assert len(clauses) == 1
        assert clauses[0]["terms"]["product_entities"] == ["Nike Air Max", "Adidas Boost"]

    def test_build_filter_clauses_product_entities_not_in(self, mock_scene_client):
        """product_entities_not_in should produce a must_not terms clause."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "product_entities_not_in": ["Counterfeit Brand"],
        })

        assert clauses == []
        assert len(must_not) == 1
        assert must_not[0]["terms"]["product_entities"] == ["Counterfeit Brand"]

    def test_build_filter_clauses_mixed_include_exclude(self, mock_scene_client):
        """Combining _in and _not_in across multiple tag fields."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "keyword_tags_in": ["할인"],
            "keyword_tags_not_in": ["광고"],
            "product_tags_in": ["cosmetics"],
            "product_entities_not_in": ["BadBrand"],
        })

        # 2 positive filter clauses: keyword_tags, product_tags
        assert len(clauses) == 2
        # 2 must_not clauses: keyword_tags, product_entities
        assert len(must_not) == 2

    def test_build_filter_clauses_empty_tag_lists_ignored(self, mock_scene_client):
        """Empty tag lists should NOT produce any clauses."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "keyword_tags_in": [],
            "keyword_tags_not_in": [],
            "product_tags_in": [],
            "product_tags_not_in": [],
            "product_entities_in": [],
            "product_entities_not_in": [],
        })

        assert clauses == []
        assert must_not == []

    def test_build_filter_clauses_tags_combined_with_existing(self, mock_scene_client):
        """Tag filters should combine with existing filter types."""
        client, _ = mock_scene_client

        clauses, must_not = client._build_filter_clauses({
            "source_types": ["gdrive"],
            "keyword_tags_in": ["라이브"],
            "product_tags_not_in": ["alcohol"],
        })

        # 2 positive: source_type terms + keyword_tags terms
        assert len(clauses) == 2
        # 1 must_not: product_tags
        assert len(must_not) == 1

    # ------------------------------------------------------------------
    # must_not propagation in search queries (PR-D)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_lexical_includes_must_not(self, mock_scene_client):
        """search_lexical should inject must_not for _not_in tag filters."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        await client.search_lexical("test query string here", "org1", {
            "keyword_tags_not_in": ["광고"],
        })

        call_body = mock_async.search.call_args.kwargs["body"]
        query = call_body["query"]["bool"]
        assert "must_not" in query
        assert query["must_not"] == [{"terms": {"keyword_tags": ["광고"]}}]

    @pytest.mark.asyncio
    async def test_search_lexical_no_must_not_when_empty(self, mock_scene_client):
        """search_lexical should NOT include must_not when no _not_in filters."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        await client.search_lexical("test query string here", "org1", {})

        call_body = mock_async.search.call_args.kwargs["body"]
        query = call_body["query"]["bool"]
        assert "must_not" not in query

    @pytest.mark.asyncio
    async def test_search_vector_includes_must_not(self, mock_scene_client):
        """search_vector should inject must_not for _not_in tag filters."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        embedding = [0.1] * 1024
        await client.search_vector(embedding, "org1", {
            "product_tags_not_in": ["alcohol"],
        })

        call_body = mock_async.search.call_args.kwargs["body"]
        knn_filter = call_body["query"]["knn"]["embedding_vector"]["filter"]["bool"]
        assert "must_not" in knn_filter
        assert knn_filter["must_not"] == [{"terms": {"product_tags": ["alcohol"]}}]

    @pytest.mark.asyncio
    async def test_search_vector_no_must_not_when_empty(self, mock_scene_client):
        """search_vector should NOT include must_not when no _not_in filters."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        embedding = [0.1] * 1024
        await client.search_vector(embedding, "org1", {})

        call_body = mock_async.search.call_args.kwargs["body"]
        knn_filter = call_body["query"]["knn"]["embedding_vector"]["filter"]["bool"]
        assert "must_not" not in knn_filter

    @pytest.mark.asyncio
    async def test_get_facets_includes_must_not(self, mock_scene_client):
        """get_facets should inject must_not for _not_in tag filters."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={
            "aggregations": {
                "libraries": {"buckets": []},
                "source_types": {"buckets": []},
                "people": {"buckets": []},
            }
        })

        await client.get_facets("org1", {
            "product_entities_not_in": ["BadBrand"],
        })

        call_body = mock_async.search.call_args.kwargs["body"]
        bool_query = call_body["query"]["bool"]
        assert "must_not" in bool_query
        assert bool_query["must_not"] == [{"terms": {"product_entities": ["BadBrand"]}}]

    @pytest.mark.asyncio
    async def test_search_lexical_includes_tag_filter_clauses(self, mock_scene_client):
        """search_lexical should include tag _in filters in filter clauses."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={"hits": {"hits": []}})

        await client.search_lexical("test query string here", "org1", {
            "keyword_tags_in": ["할인", "프로모션"],
        })

        call_body = mock_async.search.call_args.kwargs["body"]
        filter_clauses = call_body["query"]["bool"]["filter"]
        tag_terms = [c for c in filter_clauses if "keyword_tags" in c.get("terms", {})]
        assert len(tag_terms) == 1
        assert tag_terms[0]["terms"]["keyword_tags"] == ["할인", "프로모션"]

    # ------------------------------------------------------------------
    # Facets
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_facets(self, mock_scene_client):
        """get_facets should return aggregation buckets."""
        client, mock_async = mock_scene_client

        mock_async.search = AsyncMock(return_value={
            "aggregations": {
                "libraries": {"buckets": [{"key": "lib1", "doc_count": 5}]},
                "source_types": {"buckets": [{"key": "gdrive", "doc_count": 10}]},
                "people": {"buckets": [{"key": "cluster_001", "doc_count": 3}]},
            }
        })

        facets = await client.get_facets("org1", {})

        assert len(facets["libraries"]) == 1
        assert facets["libraries"][0]["key"] == "lib1"
        assert len(facets["source_types"]) == 1
        assert len(facets["people"]) == 1

    # ------------------------------------------------------------------
    # Segment client isolation
    # ------------------------------------------------------------------
    def test_scene_client_independent_of_segment_client(self, mock_scene_client):
        """SceneSearchClient should NOT share index names with OpenSearchClient."""
        client, _ = mock_scene_client

        # Scene client names
        assert "_scenes" in client.alias_name
        assert "_scenes_" in client.index_name

        # Should NOT contain segment references
        assert "_segments" not in client.alias_name
        assert "_segments" not in client.index_name


# ======================================================================
# SearchFilters schema validation tests (PR-D)
# ======================================================================


class TestSearchFiltersTagValidation:
    """Tests for tag-related field validation on SearchFilters."""

    def test_defaults_are_empty_lists(self):
        """All tag fields should default to empty lists."""
        from app.modules.search.schemas import SearchFilters

        f = SearchFilters()
        assert f.keyword_tags_in == []
        assert f.keyword_tags_not_in == []
        assert f.product_tags_in == []
        assert f.product_tags_not_in == []
        assert f.product_entities_in == []
        assert f.product_entities_not_in == []

    def test_valid_tag_lists_accepted(self):
        """Normal tag lists should be accepted."""
        from app.modules.search.schemas import SearchFilters

        f = SearchFilters(
            keyword_tags_in=["할인", "프로모션"],
            product_tags_not_in=["alcohol"],
            product_entities_in=["Nike Air Max"],
        )
        assert f.keyword_tags_in == ["할인", "프로모션"]
        assert f.product_tags_not_in == ["alcohol"]
        assert f.product_entities_in == ["Nike Air Max"]

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped."""
        from app.modules.search.schemas import SearchFilters

        f = SearchFilters(keyword_tags_in=["  할인  ", "  프로모션"])
        assert f.keyword_tags_in == ["할인", "프로모션"]

    def test_empty_strings_dropped(self):
        """Empty strings (including whitespace-only) should be dropped."""
        from app.modules.search.schemas import SearchFilters

        f = SearchFilters(keyword_tags_in=["할인", "", "   ", "프로모션"])
        assert f.keyword_tags_in == ["할인", "프로모션"]

    def test_long_tags_truncated(self):
        """Tags longer than 64 chars should be truncated."""
        from app.modules.search.schemas import SearchFilters

        long_tag = "A" * 100
        f = SearchFilters(keyword_tags_in=[long_tag])
        assert len(f.keyword_tags_in[0]) == 64
        assert f.keyword_tags_in[0] == "A" * 64

    def test_oversized_list_rejected(self):
        """Lists exceeding 50 items should be rejected by pydantic."""
        from pydantic import ValidationError
        from app.modules.search.schemas import SearchFilters

        with pytest.raises(ValidationError):
            SearchFilters(keyword_tags_in=[f"tag_{i}" for i in range(51)])

    def test_backward_compatible_no_tags(self):
        """SearchFilters without any tag fields should behave as before."""
        from app.modules.search.schemas import SearchFilters

        f = SearchFilters(source_types=["gdrive"])
        assert f.source_types == ["gdrive"]
        assert f.keyword_tags_in == []
        assert f.product_entities_not_in == []
