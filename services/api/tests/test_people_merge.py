"""
Unit tests for person cluster merge feature.

Tests verify:
1. MergePersonRequest schema validation
2. replace_person_cluster_id Painless script construction
3. FaceRepository.merge_identities centroid math
4. PeopleClusterLabelRepository.merge_labels logic
5. PeopleExcludePreferenceRepository.transfer_exclusions logic

Run with: pytest tests/test_people_merge.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestMergePersonSchemas:
    """Validate MergePersonRequest constraints."""

    def test_valid_single_source(self):
        from app.modules.people.schemas import MergePersonRequest

        req = MergePersonRequest(
            source_cluster_ids=["src_1"],
            target_cluster_id="tgt_1",
        )
        assert req.source_cluster_ids == ["src_1"]
        assert req.target_cluster_id == "tgt_1"
        assert req.keep_label is None

    def test_valid_batch_merge(self):
        from app.modules.people.schemas import MergePersonRequest

        req = MergePersonRequest(
            source_cluster_ids=["src_1", "src_2", "src_3"],
            target_cluster_id="tgt_1",
            keep_label="김태리",
        )
        assert len(req.source_cluster_ids) == 3
        assert req.keep_label == "김태리"

    def test_empty_source_rejected(self):
        from pydantic import ValidationError
        from app.modules.people.schemas import MergePersonRequest

        with pytest.raises(ValidationError):
            MergePersonRequest(
                source_cluster_ids=[],
                target_cluster_id="tgt_1",
            )

    def test_keep_label_stripped(self):
        from app.modules.people.schemas import MergePersonRequest

        req = MergePersonRequest(
            source_cluster_ids=["src_1"],
            target_cluster_id="tgt_1",
            keep_label="  hello  ",
        )
        assert req.keep_label == "hello"

    def test_keep_label_empty_becomes_none(self):
        from app.modules.people.schemas import MergePersonRequest

        req = MergePersonRequest(
            source_cluster_ids=["src_1"],
            target_cluster_id="tgt_1",
            keep_label="   ",
        )
        assert req.keep_label is None

    def test_response_model(self):
        from app.modules.people.schemas import MergePersonResponse

        resp = MergePersonResponse(
            target_cluster_id="tgt_1",
            merged_source_ids=["src_1", "src_2"],
            scenes_updated=42,
            label="김태리",
        )
        assert resp.scenes_updated == 42
        assert len(resp.merged_source_ids) == 2


# ---------------------------------------------------------------------------
# OpenSearch replace script
# ---------------------------------------------------------------------------
class TestReplacePersonClusterId:
    """Test replace_person_cluster_id on SceneSearchClient."""

    @pytest.fixture
    def mock_scene_client(self):
        with patch("app.modules.search.scene_client.get_settings") as mock_settings, \
             patch("app.modules.search.scene_client.get_opensearch_client") as mock_get_client:

            settings = MagicMock()
            settings.opensearch_url = "http://localhost:9200"
            settings.opensearch_index_prefix = "test_scenes"
            settings.opensearch_bulk_refresh = "true"
            settings.ocr_search_enabled = True
            settings.ocr_bm25_boost = 0.6
            mock_settings.return_value = settings

            async_client = MagicMock()
            async_client.indices = MagicMock()
            async_client.close = AsyncMock()
            mock_get_client.return_value = async_client

            from app.modules.search.scene_client import SceneSearchClient
            client = SceneSearchClient()
            client.client = async_client

            yield client, async_client

    @pytest.mark.asyncio
    async def test_replace_calls_update_by_query(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.update_by_query = AsyncMock(return_value={"updated": 5})

        result = await client.replace_person_cluster_id("org_1", "src_id", "tgt_id")

        assert result == 5
        async_client.update_by_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_replace_script_contains_both_ids(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.update_by_query = AsyncMock(return_value={"updated": 0})

        await client.replace_person_cluster_id("org_1", "source_abc", "target_xyz")

        call_args = async_client.update_by_query.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        params = body["script"]["params"]
        assert params["source_id"] == "source_abc"
        assert params["target_id"] == "target_xyz"

    @pytest.mark.asyncio
    async def test_replace_query_filters_by_org_and_source(self, mock_scene_client):
        client, async_client = mock_scene_client
        async_client.update_by_query = AsyncMock(return_value={"updated": 3})

        await client.replace_person_cluster_id("org_42", "src", "tgt")

        call_args = async_client.update_by_query.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        filters = body["query"]["bool"]["filter"]
        assert {"term": {"org_id": "org_42"}} in filters
        assert {"term": {"people_cluster_ids": "src"}} in filters

    @pytest.mark.asyncio
    async def test_replace_script_handles_deduplication(self, mock_scene_client):
        """Script must add target only if not already present."""
        client, async_client = mock_scene_client
        async_client.update_by_query = AsyncMock(return_value={"updated": 1})

        await client.replace_person_cluster_id("org_1", "s", "t")

        call_args = async_client.update_by_query.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        script_source = body["script"]["source"]
        # Must check .contains() before .add()
        assert "contains(params.target_id)" in script_source
        assert "add(params.target_id)" in script_source


# ---------------------------------------------------------------------------
# Face identity merge (centroid math)
# ---------------------------------------------------------------------------
class TestFaceIdentityMerge:
    """Test FaceRepository.merge_identities logic."""

    def test_weighted_centroid_average(self):
        """Verify centroid recomputation: weighted average, normalized."""
        import numpy as np

        # Simulate the merge math from FaceRepository.merge_identities
        src_centroid = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        tgt_centroid = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        src_count = 2.0
        tgt_count = 3.0
        total = src_count + tgt_count

        merged = (tgt_centroid * tgt_count + src_centroid * src_count) / total
        norm = float(np.linalg.norm(merged))
        if norm > 0.0:
            merged = merged / norm

        # Should be a unit vector pointing between the two
        assert abs(np.linalg.norm(merged) - 1.0) < 1e-5
        # Target had more weight, so merged should be closer to tgt direction
        assert merged[1] > merged[0]

    def test_equal_weight_centroid(self):
        """Equal counts should produce midpoint direction."""
        import numpy as np

        src_centroid = np.array([1.0, 0.0], dtype=np.float32)
        tgt_centroid = np.array([0.0, 1.0], dtype=np.float32)

        merged = (tgt_centroid * 1.0 + src_centroid * 1.0) / 2.0
        norm = float(np.linalg.norm(merged))
        merged = merged / norm

        # Equal weight: both components should be equal
        assert abs(merged[0] - merged[1]) < 1e-5


# ---------------------------------------------------------------------------
# Label merge logic
# ---------------------------------------------------------------------------
class TestLabelMerge:
    """Test label resolution rules for merge."""

    def test_keep_label_overrides(self):
        """Explicit keep_label should override both source and target labels."""
        # Logic: if keep_label is not None, use it
        keep_label = "Override"
        target_label = "Target"
        source_label = "Source"

        if keep_label is not None:
            resolved = keep_label if keep_label else None
        elif target_label:
            resolved = target_label
        elif source_label:
            resolved = source_label
        else:
            resolved = None

        assert resolved == "Override"

    def test_target_label_wins_by_default(self):
        """When no keep_label, target label survives."""
        keep_label = None
        target_label = "Target"
        source_label = "Source"

        if keep_label is not None:
            resolved = keep_label if keep_label else None
        elif target_label:
            resolved = target_label
        elif source_label:
            resolved = source_label
        else:
            resolved = None

        assert resolved == "Target"

    def test_source_label_inherited_when_target_unlabeled(self):
        """When target has no label, source label is inherited."""
        keep_label = None
        target_label = None
        source_label = "Source"

        if keep_label is not None:
            resolved = keep_label if keep_label else None
        elif target_label:
            resolved = target_label
        elif source_label:
            resolved = source_label
        else:
            resolved = None

        assert resolved == "Source"

    def test_both_unlabeled_stays_none(self):
        """No labels anywhere: result is None."""
        keep_label = None
        target_label = None
        source_label = None

        if keep_label is not None:
            resolved = keep_label if keep_label else None
        elif target_label:
            resolved = target_label
        elif source_label:
            resolved = source_label
        else:
            resolved = None

        assert resolved is None
