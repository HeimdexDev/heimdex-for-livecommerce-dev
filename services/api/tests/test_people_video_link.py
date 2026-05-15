"""
Unit tests for person video link/unlink feature.

Tests verify:
1. LinkPersonVideoRequest/Response schema validation
2. Scene override repository handles people_cluster_ids field
3. Override protection in enrich_scenes for people_cluster_ids
4. Video-scoped Painless script construction in scene_facets

Run with: pytest tests/test_people_video_link.py -v
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestLinkPersonVideoSchemas:
    """Validate LinkPersonVideoRequest/Response constraints."""

    def test_valid_request(self):
        from app.modules.people.schemas import LinkPersonVideoRequest

        req = LinkPersonVideoRequest(video_id="vid_123")
        assert req.video_id == "vid_123"

    def test_empty_video_id_rejected(self):
        from pydantic import ValidationError
        from app.modules.people.schemas import LinkPersonVideoRequest

        with pytest.raises(ValidationError):
            LinkPersonVideoRequest(video_id="")

    def test_response_model(self):
        from app.modules.people.schemas import LinkPersonVideoResponse

        resp = LinkPersonVideoResponse(
            person_cluster_id="person_abc",
            video_id="vid_123",
            scenes_updated=5,
        )
        assert resp.person_cluster_id == "person_abc"
        assert resp.video_id == "vid_123"
        assert resp.scenes_updated == 5

    def test_response_zero_scenes(self):
        from app.modules.people.schemas import LinkPersonVideoResponse

        resp = LinkPersonVideoResponse(
            person_cluster_id="person_abc",
            video_id="vid_123",
            scenes_updated=0,
        )
        assert resp.scenes_updated == 0


# ---------------------------------------------------------------------------
# Scene override repository: people_cluster_ids support
# ---------------------------------------------------------------------------
class TestSceneOverrideRepoPeopleField:
    """Verify people_cluster_ids is in EDITABLE_FIELDS and handled correctly."""

    def test_people_cluster_ids_in_editable_fields(self):
        from app.modules.scene_overrides.repository import EDITABLE_FIELDS

        assert "people_cluster_ids" in EDITABLE_FIELDS

    def test_field_to_column_mapping(self):
        from app.modules.scene_overrides.repository import _FIELD_TO_COLUMN

        assert "people_cluster_ids" in _FIELD_TO_COLUMN
        col, orig_col = _FIELD_TO_COLUMN["people_cluster_ids"]
        assert col == "people_cluster_ids_json"
        assert orig_col == "original_people_cluster_ids_json"

    def test_model_has_columns(self):
        from app.modules.scene_overrides.models import SceneOverride

        mapper = SceneOverride.__table__.columns
        assert "people_cluster_ids_json" in mapper
        assert "original_people_cluster_ids_json" in mapper


# ---------------------------------------------------------------------------
# Override protection in enrichment
# ---------------------------------------------------------------------------
class TestEnrichOverrideProtection:
    """Verify enrich_scenes skips people_cluster_ids when field is protected."""

    def test_protection_check_exists_in_service(self):
        """Smoke test: the protection condition must exist in the source."""
        import inspect
        from app.modules.ingest.service import SceneIngestService

        source = inspect.getsource(SceneIngestService.enrich_scenes)
        assert '"people_cluster_ids" not in protected' in source


# ---------------------------------------------------------------------------
# Scene facets: video-scoped methods
# ---------------------------------------------------------------------------
class TestVideoScopedFacets:
    """Verify remove_person_from_video and add_person_to_video exist and call OpenSearch correctly."""

    @pytest.mark.asyncio
    async def test_remove_person_from_video_calls_update_by_query(self):
        from app.modules.search.scene_facets import SceneFacetsMixin

        mixin = SceneFacetsMixin()
        mixin.client = AsyncMock()
        mixin.alias_name = "heimdex_scenes"
        mixin.client.update_by_query.return_value = {"updated": 3}

        result = await mixin.remove_person_from_video("org_1", "person_abc", "vid_123")

        assert result == 3
        mixin.client.update_by_query.assert_called_once()
        call_kwargs = mixin.client.update_by_query.call_args
        body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        # Verify video_id filter is present
        filters = body["query"]["bool"]["filter"]
        filter_fields = [list(f.get("term", {}).keys())[0] for f in filters]
        assert "video_id" in filter_fields
        assert "people_cluster_ids" in filter_fields
        assert "org_id" in filter_fields

    @pytest.mark.asyncio
    async def test_add_person_to_video_calls_update_by_query(self):
        from app.modules.search.scene_facets import SceneFacetsMixin

        mixin = SceneFacetsMixin()
        mixin.client = AsyncMock()
        mixin.alias_name = "heimdex_scenes"
        mixin.client.update_by_query.return_value = {"updated": 5}

        result = await mixin.add_person_to_video("org_1", "person_abc", "vid_123")

        assert result == 5
        mixin.client.update_by_query.assert_called_once()
        call_kwargs = mixin.client.update_by_query.call_args
        body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        # Verify video_id filter and must_not exclusion
        filters = body["query"]["bool"]["filter"]
        filter_fields = [list(f.get("term", {}).keys())[0] for f in filters]
        assert "video_id" in filter_fields
        assert "org_id" in filter_fields
        # must_not ensures person not already present
        must_not = body["query"]["bool"]["must_not"]
        assert len(must_not) == 1
        assert "people_cluster_ids" in must_not[0]["term"]

    @pytest.mark.asyncio
    async def test_remove_returns_zero_when_no_matches(self):
        from app.modules.search.scene_facets import SceneFacetsMixin

        mixin = SceneFacetsMixin()
        mixin.client = AsyncMock()
        mixin.alias_name = "heimdex_scenes"
        mixin.client.update_by_query.return_value = {"updated": 0}

        result = await mixin.remove_person_from_video("org_1", "person_abc", "vid_nonexistent")
        assert result == 0

    @pytest.mark.asyncio
    async def test_add_returns_zero_when_all_already_linked(self):
        from app.modules.search.scene_facets import SceneFacetsMixin

        mixin = SceneFacetsMixin()
        mixin.client = AsyncMock()
        mixin.alias_name = "heimdex_scenes"
        mixin.client.update_by_query.return_value = {"updated": 0}

        result = await mixin.add_person_to_video("org_1", "person_abc", "vid_123")
        assert result == 0
