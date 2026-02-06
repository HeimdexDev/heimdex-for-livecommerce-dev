"""
Integration tests for OpenSearch alias migration and versioning.

These tests verify:
1. ensure_index_exists() does NOT auto-flip alias on version mismatch
2. promote_alias_to_current_version() atomically swaps alias
3. Alias mismatch detection works correctly
4. Diagnostics include mismatch flag

Run with: pytest tests/test_alias_migration.py -v

NOTE: Integration tests require running OpenSearch instance.
Skip with: pytest tests/test_alias_migration.py -v -m "not integration"
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


class TestAliasMigrationMocked:
    """
    Unit tests for alias migration logic using mocks.
    
    These tests verify the business logic without requiring
    a live OpenSearch instance.
    """

    @pytest.fixture
    def mock_opensearch_client_class(self):
        """Create a mocked OpenSearchClient with controllable behavior."""
        with patch("app.modules.search.client.get_settings") as mock_settings, \
             patch("app.modules.search.client.get_opensearch_client") as mock_get_client:
            
            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test_migration"
            mock_settings.return_value = settings
            
            # Create async mock client
            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()
            mock_get_client.return_value = async_client
            
            from app.modules.search.client import OpenSearchClient
            client = OpenSearchClient()
            client.client = async_client
            
            yield client, async_client

    @pytest.mark.asyncio
    async def test_get_alias_targets_returns_indices(self, mock_opensearch_client_class):
        """get_alias_targets should return list of indices alias points to."""
        client, mock_async = mock_opensearch_client_class
        
        # Mock alias pointing to two indices
        mock_async.indices.get_alias = AsyncMock(return_value={
            "test_migration_segments_v1": {"aliases": {"test_migration_segments": {}}},
            "test_migration_segments_v2": {"aliases": {"test_migration_segments": {}}},
        })
        
        targets = await client.get_alias_targets()
        
        assert sorted(targets) == ["test_migration_segments_v1", "test_migration_segments_v2"]

    @pytest.mark.asyncio
    async def test_get_alias_targets_returns_empty_when_missing(self, mock_opensearch_client_class):
        """get_alias_targets should return empty list when alias doesn't exist."""
        client, mock_async = mock_opensearch_client_class
        
        # Mock alias not found error
        mock_async.indices.get_alias = AsyncMock(side_effect=Exception("alias [test] not found"))
        
        targets = await client.get_alias_targets()
        
        assert targets == []

    @pytest.mark.asyncio
    async def test_get_index_info_detects_mismatch(self, mock_opensearch_client_class):
        """get_index_info should detect when alias points to wrong index."""
        client, mock_async = mock_opensearch_client_class
        
        # Mock alias pointing to old index (v1), but current version is v2
        mock_async.indices.get_alias = AsyncMock(return_value={
            "test_migration_segments_v1": {"aliases": {"test_migration_segments": {}}},
        })
        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_mapping = AsyncMock(return_value={
            client.index_name: {
                "mappings": {
                    "properties": {
                        "embedding_vector": {"dimension": 1024}
                    }
                }
            }
        })
        mock_async.count = AsyncMock(return_value={"count": 100})
        
        info = await client.get_index_info()
        
        assert info["alias_mismatch"] is True
        assert info["alias_points_to_current"] is False
        assert "test_migration_segments_v1" in info["alias_targets"]

    @pytest.mark.asyncio
    async def test_get_index_info_no_mismatch_when_current(self, mock_opensearch_client_class):
        """get_index_info should not report mismatch when alias is current."""
        client, mock_async = mock_opensearch_client_class
        
        # Mock alias pointing to current version
        mock_async.indices.get_alias = AsyncMock(return_value={
            client.index_name: {"aliases": {client.alias_name: {}}},
        })
        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_mapping = AsyncMock(return_value={
            client.index_name: {
                "mappings": {
                    "properties": {
                        "embedding_vector": {"dimension": 1024}
                    }
                }
            }
        })
        mock_async.count = AsyncMock(return_value={"count": 100})
        
        info = await client.get_index_info()
        
        assert info["alias_mismatch"] is False
        assert info["alias_points_to_current"] is True

    @pytest.mark.asyncio
    async def test_ensure_index_exists_warns_on_mismatch(self, mock_opensearch_client_class):
        """ensure_index_exists should warn but NOT auto-flip when alias points elsewhere."""
        client, mock_async = mock_opensearch_client_class
        
        # Index exists, but alias points to old version
        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_alias = AsyncMock(return_value={
            "test_migration_segments_v1": {"aliases": {"test_migration_segments": {}}},
        })
        
        result = await client.ensure_index_exists()
        
        # Should have mismatch warning
        assert result["alias_mismatch_warning"] is not None
        assert "ALIAS MISMATCH" in result["alias_mismatch_warning"]
        assert result["alias_current_targets"] == ["test_migration_segments_v1"]
        
        # Should NOT have called put_alias (no auto-flip)
        mock_async.indices.put_alias.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_index_exists_creates_alias_when_missing(self, mock_opensearch_client_class):
        """ensure_index_exists should create alias when it doesn't exist."""
        client, mock_async = mock_opensearch_client_class
        
        # Index exists, alias doesn't exist
        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_alias = AsyncMock(side_effect=Exception("alias not found"))
        mock_async.indices.put_alias = AsyncMock()
        
        result = await client.ensure_index_exists()
        
        # Should have created alias
        assert result["alias_created"] is True
        mock_async.indices.put_alias.assert_called_once()

    @pytest.mark.asyncio
    async def test_promote_alias_atomic_swap(self, mock_opensearch_client_class):
        """promote_alias_to_current_version should perform atomic swap."""
        client, mock_async = mock_opensearch_client_class
        
        # Set up: alias points to old version
        mock_async.indices.exists = AsyncMock(return_value=True)
        
        # Track state changes
        alias_state = {"targets": ["test_migration_segments_v1"]}
        
        async def mock_get_alias(*args, **kwargs):
            if alias_state["targets"]:
                return {idx: {"aliases": {}} for idx in alias_state["targets"]}
            raise Exception("alias not found")
        
        async def mock_update_aliases(body=None):
            # Simulate atomic swap
            alias_state["targets"] = [client.index_name]
            return {"acknowledged": True}
        
        mock_async.indices.get_alias = mock_get_alias
        mock_async.indices.update_aliases = mock_update_aliases
        
        result = await client.promote_alias_to_current_version()
        
        assert result["success"] is True
        assert result["before_targets"] == ["test_migration_segments_v1"]
        assert result["after_targets"] == [client.index_name]

    @pytest.mark.asyncio
    async def test_promote_alias_noop_when_current(self, mock_opensearch_client_class):
        """promote_alias_to_current_version should be no-op when already current."""
        client, mock_async = mock_opensearch_client_class
        
        # Alias already points to current version
        mock_async.indices.exists = AsyncMock(return_value=True)
        mock_async.indices.get_alias = AsyncMock(return_value={
            client.index_name: {"aliases": {client.alias_name: {}}},
        })
        
        result = await client.promote_alias_to_current_version()
        
        assert result["success"] is True
        assert result["already_current"] is True
        
        # update_aliases should NOT have been called
        mock_async.indices.update_aliases.assert_not_called()

    @pytest.mark.asyncio
    async def test_promote_alias_fails_if_index_missing(self, mock_opensearch_client_class):
        """promote_alias_to_current_version should fail if target index doesn't exist."""
        client, mock_async = mock_opensearch_client_class
        
        # Index doesn't exist
        mock_async.indices.exists = AsyncMock(return_value=False)
        mock_async.indices.get_alias = AsyncMock(return_value={})
        
        with pytest.raises(ValueError, match="does not exist"):
            await client.promote_alias_to_current_version()


@pytest.mark.integration
class TestAliasMigrationLive:
    """
    Live integration tests for alias migration.
    
    These tests require a running OpenSearch instance.
    Run with: pytest tests/test_alias_migration.py::TestAliasMigrationLive -v
    """

    @pytest.fixture
    async def live_clients(self):
        """
        Create two OpenSearchClient instances simulating v2 and v3.
        
        Uses test prefix and cleans up after tests.
        """
        with patch("app.modules.search.client.get_settings") as mock_settings:
            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = f"test_alias_{uuid4().hex[:8]}"
            mock_settings.return_value = settings
            
            from app.modules.search.client import OpenSearchClient
            
            # Create client with "v2" version
            with patch.object(OpenSearchClient, "INDEX_VERSION", "v2"):
                client_v2 = OpenSearchClient()
            
            # Create client with "v3" version
            with patch.object(OpenSearchClient, "INDEX_VERSION", "v3"):
                client_v3 = OpenSearchClient()
            
            try:
                yield client_v2, client_v3
            finally:
                # Cleanup: delete test indices
                try:
                    await client_v2.client.indices.delete(index=f"{settings.opensearch_index_prefix}_*")
                except Exception:
                    pass
                await client_v2.close()
                await client_v3.close()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_full_migration_workflow(self, live_clients):
        """
        Integration test: Full migration from v2 to v3.
        
        1. Create v2 index with alias
        2. Create v3 index (new version)
        3. Verify ensure_index_exists() does NOT move alias
        4. Call promote_alias_to_current_version()
        5. Verify alias now points only to v3
        """
        client_v2, client_v3 = live_clients
        
        # Step 1: Create v2 index with alias
        await client_v2.ensure_index_exists()
        
        targets_after_v2 = await client_v2.get_alias_targets()
        assert targets_after_v2 == [client_v2.index_name]
        
        # Step 2: Create v3 index (manually, simulating version bump)
        # This uses client_v3 which has INDEX_VERSION="v3"
        # First create the index without alias
        await client_v3.client.indices.create(
            index=client_v3.index_name,
            body={
                "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
                "mappings": {"properties": {"test_field": {"type": "keyword"}}},
            }
        )
        
        # Step 3: Verify ensure_index_exists() does NOT move alias
        result = await client_v3.ensure_index_exists()
        
        # Should detect mismatch
        assert result.get("alias_mismatch_warning") is not None
        assert "ALIAS MISMATCH" in result["alias_mismatch_warning"]
        
        # Alias should still point to v2
        targets_before_promote = await client_v3.get_alias_targets()
        assert client_v2.index_name in targets_before_promote
        assert client_v3.index_name not in targets_before_promote
        
        # Step 4: Explicitly promote alias
        promote_result = await client_v3.promote_alias_to_current_version()
        
        assert promote_result["success"] is True
        assert client_v2.index_name in promote_result["before_targets"]
        assert promote_result["after_targets"] == [client_v3.index_name]
        
        # Step 5: Verify alias now points only to v3
        final_targets = await client_v3.get_alias_targets()
        assert final_targets == [client_v3.index_name]
        
        # Old v2 alias target should be gone
        assert client_v2.index_name not in final_targets

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_get_index_info_includes_mismatch_flag(self, live_clients):
        """get_index_info should include mismatch flag in diagnostics."""
        client_v2, client_v3 = live_clients
        
        # Create v2 with alias
        await client_v2.ensure_index_exists()
        
        # Create v3 index manually (no alias)
        await client_v3.client.indices.create(
            index=client_v3.index_name,
            body={
                "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
                "mappings": {"properties": {"test_field": {"type": "keyword"}}},
            }
        )
        
        # Get info from v3's perspective (expecting mismatch)
        info = await client_v3.get_index_info()
        
        assert info["alias_mismatch"] is True
        assert info["alias_points_to_current"] is False
        assert info["intended_index"] == client_v3.index_name
        assert client_v2.index_name in info["alias_targets"]
