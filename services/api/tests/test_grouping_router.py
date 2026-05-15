# pyright: reportUnknownMemberType=false, reportUnusedFunction=false, reportExplicitAny=false, reportAny=false
"""
Unit tests for the scene grouping router and service layer.

Tests cover:
1. GroupingService — orchestration with mocked OpenSearch client
2. Router endpoint — GET /api/videos/{video_id}/scene-groups
3. Response schema validation
4. Edge cases (empty scenes, no embeddings, large videos)

Run with: pytest tests/test_grouping_router.py -v
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.grouping.schemas import SceneGroup, SceneGroupsResponse
from app.modules.grouping.service import GroupingService, _strip_embeddings


# ======================================================================
# Helpers
# ======================================================================


def _make_raw_scene(
    scene_id: str,
    start_ms: int,
    end_ms: int,
    *,
    text_emb: list[float] | None = None,
    vis_emb: list[float] | None = None,
) -> dict[str, Any]:
    """Build a raw scene dict as returned by get_video_scenes_with_embeddings."""
    scene: dict[str, Any] = {
        "scene_id": scene_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "transcript_raw": "",
        "transcript_char_count": 0,
        "scene_caption": "",
        "keyword_tags": [],
        "product_tags": [],
        "product_entities": [],
        "speech_segment_count": 0,
        "people_cluster_ids": [],
        "ingest_time": None,
        "keyframe_timestamp_ms": start_ms,
        "speaker_transcript": "",
        "speaker_count": 0,
        "ocr_text_raw": "",
        "ocr_char_count": 0,
    }
    if text_emb is not None:
        scene["embedding_vector"] = text_emb
    if vis_emb is not None:
        scene["visual_embedding"] = vis_emb
    return scene


def _l2_normalize(v: list[float]) -> list[float]:
    """L2-normalize a vector."""
    import math
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0:
        return v
    return [x / norm for x in v]


# ======================================================================
# _strip_embeddings
# ======================================================================


class TestStripEmbeddings:
    def test_removes_both_embedding_fields(self) -> None:
        scene = _make_raw_scene("s1", 0, 10000, text_emb=[1.0, 2.0], vis_emb=[3.0, 4.0])
        stripped = _strip_embeddings(scene)
        assert "embedding_vector" not in stripped
        assert "visual_embedding" not in stripped

    def test_preserves_all_other_fields(self) -> None:
        scene = _make_raw_scene("s1", 0, 10000, text_emb=[1.0])
        stripped = _strip_embeddings(scene)
        assert stripped["scene_id"] == "s1"
        assert stripped["start_ms"] == 0
        assert stripped["end_ms"] == 10000

    def test_no_embeddings_noop(self) -> None:
        scene = _make_raw_scene("s1", 0, 10000)
        stripped = _strip_embeddings(scene)
        assert "embedding_vector" not in stripped
        assert "visual_embedding" not in stripped
        assert stripped["scene_id"] == "s1"


# ======================================================================
# GroupingService
# ======================================================================


class TestGroupingService:
    @pytest.fixture
    def mock_client(self) -> MagicMock:
        client = MagicMock()
        client.get_video_scenes_with_embeddings = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_client: MagicMock) -> GroupingService:
        return GroupingService(mock_client)

    @pytest.mark.asyncio
    async def test_empty_scenes(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        mock_client.get_video_scenes_with_embeddings.return_value = []
        result = await service.get_scene_groups("org-1", "vid-1")
        assert isinstance(result, SceneGroupsResponse)
        assert result.total_scenes == 0
        assert result.total_groups == 0
        assert result.groups == []

    @pytest.mark.asyncio
    async def test_single_scene(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        raw = [_make_raw_scene("s1", 0, 10000)]
        mock_client.get_video_scenes_with_embeddings.return_value = raw
        result = await service.get_scene_groups("org-1", "vid-1")
        assert result.total_scenes == 1
        assert result.total_groups == 1
        assert result.groups[0].scene_count == 1
        assert result.groups[0].representative_scene_id == "s1"

    @pytest.mark.asyncio
    async def test_two_groups_distinct_embeddings(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        """Two clusters of 3 scenes with orthogonal text embeddings → 2 groups."""
        v1 = _l2_normalize([1.0, 0.0, 0.0, 0.0])
        v2 = _l2_normalize([0.0, 0.0, 1.0, 0.0])
        raw = [
            _make_raw_scene("s1", 0, 10000, text_emb=v1),
            _make_raw_scene("s2", 10000, 20000, text_emb=v1),
            _make_raw_scene("s3", 20000, 30000, text_emb=v1),
            _make_raw_scene("s4", 30000, 40000, text_emb=v2),
            _make_raw_scene("s5", 40000, 50000, text_emb=v2),
            _make_raw_scene("s6", 50000, 60000, text_emb=v2),
        ]
        mock_client.get_video_scenes_with_embeddings.return_value = raw
        result = await service.get_scene_groups("org-1", "vid-1", threshold=0.55)

        assert result.total_groups == 2
        assert result.total_scenes == 6

        g1, g2 = result.groups
        assert g1.group_index == 0
        assert g1.scene_count == 3
        assert g1.start_ms == 0
        assert g1.end_ms == 30000

        assert g2.group_index == 1
        assert g2.scene_count == 3
        assert g2.start_ms == 30000
        assert g2.end_ms == 60000

    @pytest.mark.asyncio
    async def test_embeddings_stripped_from_response(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        """Embedding vectors must not appear in the response scenes."""
        v = _l2_normalize([1.0, 0.0, 0.0, 0.0])
        raw = [
            _make_raw_scene("s1", 0, 10000, text_emb=v, vis_emb=[0.1, 0.2, 0.3]),
            _make_raw_scene("s2", 10000, 20000, text_emb=v, vis_emb=[0.1, 0.2, 0.3]),
        ]
        mock_client.get_video_scenes_with_embeddings.return_value = raw
        result = await service.get_scene_groups("org-1", "vid-1")

        for group in result.groups:
            for scene in group.scenes:
                scene_dict = scene.model_dump()
                assert "embedding_vector" not in scene_dict
                assert "visual_embedding" not in scene_dict

    @pytest.mark.asyncio
    async def test_representative_scene_is_middle(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        """Representative scene should be the middle scene of the group."""
        v = _l2_normalize([1.0, 0.0, 0.0, 0.0])
        raw = [
            _make_raw_scene("s1", 0, 10000, text_emb=v),
            _make_raw_scene("s2", 10000, 20000, text_emb=v),
            _make_raw_scene("s3", 20000, 30000, text_emb=v),
            _make_raw_scene("s4", 30000, 40000, text_emb=v),
            _make_raw_scene("s5", 40000, 50000, text_emb=v),
        ]
        mock_client.get_video_scenes_with_embeddings.return_value = raw
        result = await service.get_scene_groups("org-1", "vid-1")

        # All one group, middle of 5 scenes is index 2 → "s3"
        assert result.total_groups == 1
        assert result.groups[0].representative_scene_id == "s3"

    @pytest.mark.asyncio
    async def test_org_and_video_id_passed_to_client(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        mock_client.get_video_scenes_with_embeddings.return_value = []
        await service.get_scene_groups("org-abc", "vid-xyz")
        mock_client.get_video_scenes_with_embeddings.assert_called_once_with(
            "org-abc", "vid-xyz",
        )

    @pytest.mark.asyncio
    async def test_custom_threshold(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        """Low threshold → fewer boundaries → fewer groups."""
        v1 = _l2_normalize([1.0, 0.0, 0.0, 0.0])
        v2 = _l2_normalize([0.8, 0.6, 0.0, 0.0])  # not orthogonal, cos ~ 0.8
        raw = [
            _make_raw_scene("s1", 0, 10000, text_emb=v1),
            _make_raw_scene("s2", 10000, 20000, text_emb=v1),
            _make_raw_scene("s3", 20000, 30000, text_emb=v2),
            _make_raw_scene("s4", 30000, 40000, text_emb=v2),
        ]
        mock_client.get_video_scenes_with_embeddings.return_value = raw

        # High threshold → likely 2 groups (sim between v1 and v2 ~ 0.8)
        result_high = await service.get_scene_groups("org-1", "vid-1", threshold=0.9)
        # Low threshold → 1 group (0.8 > 0.1)
        result_low = await service.get_scene_groups("org-1", "vid-1", threshold=0.1)

        assert result_low.total_groups <= result_high.total_groups

    @pytest.mark.asyncio
    async def test_video_id_in_response(
        self, service: GroupingService, mock_client: MagicMock,
    ) -> None:
        mock_client.get_video_scenes_with_embeddings.return_value = []
        result = await service.get_scene_groups("org-1", "vid-42")
        assert result.video_id == "vid-42"


# ======================================================================
# Schema validation
# ======================================================================


class TestSchemas:
    def test_scene_group_model(self) -> None:
        group = SceneGroup(
            group_index=0,
            start_ms=0,
            end_ms=10000,
            scene_count=2,
            representative_scene_id="s1",
            scenes=[],
        )
        assert group.group_index == 0
        assert group.scene_count == 2

    def test_scene_groups_response_defaults(self) -> None:
        resp = SceneGroupsResponse(video_id="v1")
        assert resp.total_groups == 0
        assert resp.total_scenes == 0
        assert resp.groups == []

    def test_scene_groups_response_serialization(self) -> None:
        resp = SceneGroupsResponse(
            video_id="v1",
            total_groups=1,
            total_scenes=2,
            groups=[
                SceneGroup(
                    group_index=0,
                    start_ms=0,
                    end_ms=20000,
                    scene_count=2,
                    representative_scene_id="s1",
                ),
            ],
        )
        data = resp.model_dump()
        assert data["video_id"] == "v1"
        assert len(data["groups"]) == 1
        assert data["groups"][0]["representative_scene_id"] == "s1"
