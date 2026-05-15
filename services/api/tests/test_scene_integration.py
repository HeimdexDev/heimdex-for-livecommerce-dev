"""
Integration tests for the SceneSearchClient against a live OpenSearch instance.

These tests require a running OpenSearch instance and are excluded from normal
test runs. Run explicitly with:

    pytest tests/test_scene_integration.py -m integration -v

Tests verify:
1. Index creation with correct mapping and settings
2. Alias creation and correctness
3. Scene document indexing (single and bulk)
4. Lexical search returning correct hits
5. Vector search returning correct hits
6. Org_id tenant isolation
7. Idempotent index creation
8. Cleanup of test indices

Each test run creates a unique index prefix to avoid collisions.
"""
import pytest
import pytest_asyncio
from uuid import uuid4
from unittest.mock import patch, MagicMock


@pytest.fixture
def unique_prefix():
    """Generate a unique index prefix for test isolation."""
    return f"test_{uuid4().hex[:8]}"


@pytest_asyncio.fixture
async def scene_client(unique_prefix):
    """Create a SceneSearchClient with a unique test prefix, tear down after."""
    with patch("app.modules.search.scene_client.get_settings") as mock_settings:
        settings = MagicMock()
        settings.opensearch_url = "http://opensearch:9200"
        settings.opensearch_index_prefix = unique_prefix
        settings.opensearch_bulk_refresh = "true"
        mock_settings.return_value = settings

        from app.modules.search.scene_client import SceneSearchClient
        client = SceneSearchClient()

        yield client

        # Cleanup: delete test index
        try:
            await client.client.indices.delete(index=client.index_name)
        except Exception:
            pass
        await client.close()


@pytest.mark.integration
class TestSceneSearchClientLive:
    """Integration tests requiring a live OpenSearch instance."""

    # ------------------------------------------------------------------
    # Index creation
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_index_succeeds(self, scene_client):
        """Creating a scene index should succeed against live OpenSearch."""
        await scene_client.create_index()

        exists = await scene_client.client.indices.exists(index=scene_client.index_name)
        assert exists is True

    @pytest.mark.asyncio
    async def test_create_index_is_idempotent(self, scene_client):
        """Creating the same index twice should not raise."""
        await scene_client.create_index()
        await scene_client.create_index()  # Should not raise

        exists = await scene_client.client.indices.exists(index=scene_client.index_name)
        assert exists is True

    # ------------------------------------------------------------------
    # Alias
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_alias_created_with_index(self, scene_client):
        """Alias should be created alongside the index."""
        await scene_client.create_index()

        alias_info = await scene_client.client.indices.get_alias(
            name=scene_client.alias_name
        )
        assert scene_client.index_name in alias_info

    @pytest.mark.asyncio
    async def test_ensure_index_exists_creates_both(self, scene_client):
        """ensure_index_exists should create index and alias when missing."""
        result = await scene_client.ensure_index_exists()

        assert result["index_created"] is True
        assert result["alias_created"] is True

        exists = await scene_client.client.indices.exists(index=scene_client.index_name)
        assert exists is True

    # ------------------------------------------------------------------
    # Mapping verification
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_mapping_has_required_fields(self, scene_client):
        """Index mapping should contain all scene-specific fields."""
        await scene_client.create_index()

        mapping = await scene_client.client.indices.get_mapping(
            index=scene_client.index_name
        )
        props = mapping[scene_client.index_name]["mappings"]["properties"]

        # Core fields
        assert props["scene_id"]["type"] == "keyword"
        assert props["video_id"]["type"] == "keyword"
        assert props["org_id"]["type"] == "keyword"
        assert props["library_id"]["type"] == "keyword"
        assert props["start_ms"]["type"] == "integer"
        assert props["end_ms"]["type"] == "integer"
        assert props["transcript_raw"]["type"] == "text"
        assert props["transcript_norm"]["type"] == "text"
        assert props["speech_segment_count"]["type"] == "integer"

        # kNN vector
        assert props["embedding_vector"]["type"] == "knn_vector"
        assert props["embedding_vector"]["dimension"] == 1024

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_index_single_scene_and_retrieve(self, scene_client):
        """Should be able to index a scene and retrieve it via lexical search."""
        await scene_client.ensure_index_exists()

        org_id = str(uuid4())
        doc = {
            "org_id": org_id,
            "scene_id": "test_scene_001",
            "video_id": "vid_001",
            "library_id": str(uuid4()),
            "start_ms": 0,
            "end_ms": 10000,
            "transcript_raw": "This is a test scene transcript",
            "transcript_norm": "this is a test scene transcript",
            "transcript_char_count": 31,
            "speech_segment_count": 2,
            "embedding_vector": [0.1] * 1024,
            "source_type": "gdrive",
            "people_cluster_ids": [],
        }

        await scene_client.index_scene("test_scene_001", doc)

        # Search should find it
        results = await scene_client.search_lexical(
            query="test scene transcript",
            org_id=org_id,
            filters={},
            size=10,
        )

        assert len(results) >= 1
        assert results[0]["_source"]["scene_id"] == "test_scene_001"

    @pytest.mark.asyncio
    async def test_bulk_index_scenes(self, scene_client):
        """Bulk indexing should store all documents."""
        await scene_client.ensure_index_exists()

        org_id = str(uuid4())
        docs = []
        for i in range(5):
            doc_id = f"bulk_scene_{i}"
            doc = {
                "org_id": org_id,
                "scene_id": doc_id,
                "video_id": f"vid_{i}",
                "library_id": str(uuid4()),
                "start_ms": i * 5000,
                "end_ms": (i + 1) * 5000,
                "transcript_raw": f"Bulk test transcript number {i}",
                "transcript_norm": f"bulk test transcript number {i}",
                "transcript_char_count": 30,
                "speech_segment_count": 1,
                "embedding_vector": [0.1 + i * 0.01] * 1024,
                "source_type": "gdrive",
                "people_cluster_ids": [],
            }
            docs.append((doc_id, doc))

        await scene_client.bulk_index_scenes(docs)

        # Count docs in index
        count = await scene_client.client.count(index=scene_client.index_name)
        assert count["count"] == 5

    # ------------------------------------------------------------------
    # Org_id tenant isolation
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_org_id_isolation(self, scene_client):
        """Search results should be scoped to the queried org_id."""
        await scene_client.ensure_index_exists()

        org_a = str(uuid4())
        org_b = str(uuid4())

        # Index scenes for two different orgs
        await scene_client.index_scene("scene_org_a", {
            "org_id": org_a,
            "scene_id": "scene_org_a",
            "video_id": "vid1",
            "library_id": str(uuid4()),
            "start_ms": 0,
            "end_ms": 5000,
            "transcript_raw": "shared keyword data",
            "transcript_norm": "shared keyword data",
            "transcript_char_count": 19,
            "speech_segment_count": 1,
            "embedding_vector": [0.1] * 1024,
            "source_type": "gdrive",
            "people_cluster_ids": [],
        })
        await scene_client.index_scene("scene_org_b", {
            "org_id": org_b,
            "scene_id": "scene_org_b",
            "video_id": "vid2",
            "library_id": str(uuid4()),
            "start_ms": 0,
            "end_ms": 5000,
            "transcript_raw": "shared keyword data",
            "transcript_norm": "shared keyword data",
            "transcript_char_count": 19,
            "speech_segment_count": 1,
            "embedding_vector": [0.1] * 1024,
            "source_type": "gdrive",
            "people_cluster_ids": [],
        })

        # Search as org_a should only return org_a's scene
        results_a = await scene_client.search_lexical(
            query="shared keyword",
            org_id=org_a,
            filters={},
            size=10,
        )

        assert len(results_a) == 1
        assert results_a[0]["_source"]["org_id"] == org_a

    # ------------------------------------------------------------------
    # Vector search
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_vector_search_returns_hits(self, scene_client):
        """Vector (kNN) search should return indexed scenes."""
        await scene_client.ensure_index_exists()

        org_id = str(uuid4())
        embedding = [0.5] * 1024

        await scene_client.index_scene("vec_scene_001", {
            "org_id": org_id,
            "scene_id": "vec_scene_001",
            "video_id": "vid1",
            "library_id": str(uuid4()),
            "start_ms": 0,
            "end_ms": 5000,
            "transcript_raw": "vector search test",
            "transcript_norm": "vector search test",
            "transcript_char_count": 18,
            "speech_segment_count": 1,
            "embedding_vector": embedding,
            "source_type": "gdrive",
            "people_cluster_ids": [],
        })

        results = await scene_client.search_vector(
            embedding=embedding,
            org_id=org_id,
            filters={},
            size=10,
        )

        assert len(results) >= 1
        assert results[0]["_source"]["scene_id"] == "vec_scene_001"
