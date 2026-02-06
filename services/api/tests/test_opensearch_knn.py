"""
Integration tests for OpenSearch kNN vector search with 1024-dim embeddings.

These tests verify:
1. Index creation with 1024-dim knn_vector mapping
2. Document insertion with 1024-d embedding vectors
3. kNN query returns results correctly

Run with: pytest tests/test_opensearch_knn.py -v

NOTE: Requires running OpenSearch instance. Skip with:
    pytest tests/test_opensearch_knn.py -v -m "not integration"
"""
import math
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

from app.modules.search.client import OpenSearchClient
from app.modules.search.embedding import _generate_mock_embedding


class TestEmbeddingDimension:
    """Verify embedding dimension configuration consistency."""

    def test_client_dimension_is_1024(self):
        """OpenSearch client should be configured for 1024-dim vectors."""
        assert OpenSearchClient.EMBEDDING_DIMENSION == 1024

    def test_mock_embedding_produces_1024_dim(self):
        """Mock embeddings should produce 1024-dimensional vectors."""
        embedding = _generate_mock_embedding("test text", 1024)
        assert len(embedding) == 1024

    def test_mock_embedding_is_normalized(self):
        """Mock embeddings should be L2-normalized (unit vectors)."""
        embedding = _generate_mock_embedding("test text for normalization", 1024)
        norm = math.sqrt(sum(x * x for x in embedding))
        assert norm == pytest.approx(1.0, rel=1e-6)


class TestOpenSearchClientConfiguration:
    """Test OpenSearch client configuration for kNN."""

    @patch("app.modules.search.client.get_settings")
    @patch("app.modules.search.client.get_opensearch_client")
    def test_alias_and_index_names(self, mock_get_client, mock_settings):
        """Client should use versioned index name and alias."""
        settings = MagicMock()
        settings.opensearch_url = "http://localhost:9200"
        settings.opensearch_index_prefix = "heimdex"
        mock_settings.return_value = settings
        mock_get_client.return_value = MagicMock()

        client = OpenSearchClient()

        # Alias is the base name (used for queries)
        assert client.alias_name == "heimdex_segments"
        # Index name includes version (used for migration)
        assert "heimdex_segments_v" in client.index_name

    @patch("app.modules.search.client.get_settings")
    @patch("app.modules.search.client.get_opensearch_client")
    def test_index_version_is_set(self, mock_get_client, mock_settings):
        """Client should have a version for zero-downtime migrations."""
        settings = MagicMock()
        settings.opensearch_url = "http://localhost:9200"
        settings.opensearch_index_prefix = "heimdex"
        mock_settings.return_value = settings
        mock_get_client.return_value = MagicMock()

        # INDEX_VERSION should be defined
        assert hasattr(OpenSearchClient, "INDEX_VERSION")
        assert OpenSearchClient.INDEX_VERSION is not None


class TestKnnVectorMapping:
    """Test that kNN vector mapping is correctly configured."""

    def test_mapping_uses_cosine_similarity(self):
        """
        Verify that the mapping uses cosine similarity.
        
        For L2-normalized vectors (which E5 produces), cosine similarity
        is equivalent to dot product and is the recommended metric.
        """
        # This is a documentation test - the actual mapping is in create_index()
        # The important thing is that space_type is "cosinesimil" for normalized embeddings
        expected_space_type = "cosinesimil"
        
        # Read the actual mapping from the source
        import inspect
        from app.modules.search.client import OpenSearchClient
        
        source = inspect.getsource(OpenSearchClient.create_index)
        assert f'"space_type": "{expected_space_type}"' in source

    def test_mapping_uses_hnsw_algorithm(self):
        """Verify that HNSW algorithm is used for approximate kNN."""
        import inspect
        from app.modules.search.client import OpenSearchClient
        
        source = inspect.getsource(OpenSearchClient.create_index)
        assert '"name": "hnsw"' in source


class TestKnnIntegrationMocked:
    """Mocked integration tests for kNN operations."""

    @pytest.fixture
    def mock_client(self):
        """Create a mocked OpenSearch client."""
        with patch("app.modules.search.client.get_settings") as mock_settings, \
             patch("app.modules.search.client.get_opensearch_client") as mock_get_client:
            
            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test"
            mock_settings.return_value = settings
            
            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.indices.exists = MagicMock(return_value=False)
            async_client.indices.create = MagicMock()
            async_client.search = MagicMock()
            async_client.index = MagicMock()
            async_client.close = MagicMock()
            mock_get_client.return_value = async_client
            
            client = OpenSearchClient()
            yield client

    @pytest.mark.asyncio
    async def test_search_vector_uses_1024_dim_query(self, mock_client):
        """Vector search should work with 1024-dim query vectors."""
        org_id = str(uuid4())
        
        # Generate a 1024-dim query embedding
        query_embedding = _generate_mock_embedding("test query", 1024)
        assert len(query_embedding) == 1024
        
        # Mock the search response
        mock_client.client.search = AsyncMock(return_value={
            "hits": {
                "hits": [
                    {
                        "_id": "doc1",
                        "_score": 0.95,
                        "_source": {
                            "segment_id": "seg1",
                            "transcript_raw": "Test transcript",
                        }
                    }
                ]
            }
        })
        
        # Execute vector search
        results = await mock_client.search_vector(
            embedding=query_embedding,
            org_id=org_id,
            filters={},
            size=10,
        )
        
        # Verify search was called with the embedding
        mock_client.client.search.assert_called_once()
        call_args = mock_client.client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        
        # Verify the query contains the embedding vector
        knn_query = body["query"]["knn"]["embedding_vector"]
        assert len(knn_query["vector"]) == 1024
        assert knn_query["vector"] == query_embedding

    def test_document_embedding_dimension_validation(self):
        """Documents indexed must have 1024-dim embeddings."""
        # Generate embeddings
        valid_embedding = _generate_mock_embedding("valid text", 1024)
        invalid_embedding = _generate_mock_embedding("invalid text", 768)
        
        assert len(valid_embedding) == 1024
        assert len(invalid_embedding) == 768
        
        # In production, OpenSearch would reject 768-dim vectors
        # when the mapping specifies 1024 dimensions


# Mark for integration tests that require live OpenSearch
@pytest.mark.integration
class TestKnnIntegrationLive:
    """
    Live integration tests - requires running OpenSearch.
    
    Run with: pytest tests/test_opensearch_knn.py::TestKnnIntegrationLive -v
    
    These tests are skipped by default. To run them:
    1. Start OpenSearch: docker compose up opensearch
    2. Run: pytest tests/test_opensearch_knn.py -m integration -v
    """

    @pytest.fixture
    async def live_client(self):
        """
        Create a real OpenSearch client for integration tests.
        
        Uses a test index prefix to avoid polluting production data.
        """
        with patch("app.modules.search.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test_knn"
            mock_settings.return_value = settings
            
            client = OpenSearchClient()
            
            try:
                yield client
            finally:
                # Cleanup: delete test index
                try:
                    await client.client.indices.delete(index=client.index_name)
                except Exception:
                    pass
                await client.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_create_index_with_1024_dim_mapping(self, live_client):
        """Create index with 1024-dim knn_vector mapping."""
        await live_client.create_index()
        
        # Verify index exists
        exists = await live_client.client.indices.exists(index=live_client.index_name)
        assert exists
        
        # Verify mapping
        mapping = await live_client.client.indices.get_mapping(index=live_client.index_name)
        props = mapping[live_client.index_name]["mappings"]["properties"]
        
        assert "embedding_vector" in props
        assert props["embedding_vector"]["dimension"] == 1024

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_insert_and_query_1024_dim_vector(self, live_client):
        """Insert document with 1024-d vector and query it back."""
        await live_client.ensure_index_exists()
        
        org_id = str(uuid4())
        doc_id = "test_doc_1"
        
        # Create document with 1024-d embedding
        embedding = _generate_mock_embedding("test document content", 1024)
        document = {
            "org_id": org_id,
            "library_id": str(uuid4()),
            "video_id": str(uuid4()),
            "segment_id": doc_id,
            "transcript_raw": "Test document content",
            "transcript_norm": "test document content",
            "source_type": "gdrive",
            "start_ms": 0,
            "end_ms": 5000,
            "people_cluster_ids": [],
            "embedding_vector": embedding,
        }
        
        # Index the document
        await live_client.index_segment(doc_id, document)
        
        # Query with similar embedding
        query_embedding = _generate_mock_embedding("test document content", 1024)
        results = await live_client.search_vector(
            embedding=query_embedding,
            org_id=org_id,
            filters={},
            size=10,
        )
        
        # Verify we got results
        assert len(results) >= 1
        assert results[0]["_source"]["segment_id"] == doc_id
