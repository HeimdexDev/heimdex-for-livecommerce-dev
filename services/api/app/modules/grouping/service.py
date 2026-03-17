"""
Orchestration layer for scene grouping.

Fetches scenes with embeddings from OpenSearch, delegates boundary
detection to the pure algorithm module, and builds the API response.

Dependencies: SceneSearchClient only (no Postgres, no other modules).
"""

from __future__ import annotations

from typing import Any

from app.logging_config import get_logger
from app.modules.grouping.algorithm import (
    compute_pairwise_similarity,
    find_group_boundaries,
)
from app.modules.grouping.schemas import SceneGroup, SceneGroupsResponse
from app.modules.search.scene_client import SceneSearchClient
from app.modules.videos.schemas import VideoScene

logger = get_logger(__name__)


def _strip_embeddings(scene: dict[str, Any]) -> dict[str, Any]:
    """Return a scene dict without embedding vectors."""
    return {
        k: v
        for k, v in scene.items()
        if k not in ("embedding_vector", "visual_embedding")
    }


class GroupingService:
    def __init__(self, scene_client: SceneSearchClient) -> None:
        self.scene_client = scene_client

    async def get_scene_groups(
        self,
        org_id: str,
        video_id: str,
        *,
        threshold: float | None = None,
        sensitivity: float = 1.0,
        min_group_size: int = 2,
    ) -> SceneGroupsResponse:
        """Compute semantic scene groups for a video.

        Args:
            org_id: Organization ID.
            video_id: Video ID.
            threshold: If provided, overrides adaptive threshold.
                When None (default), the threshold is computed adaptively
                from the video's own similarity distribution.
            sensitivity: Std devs below mean for adaptive threshold.
                Higher = fewer groups. Lower = more groups. Default 1.0.
            min_group_size: Minimum scenes per group (smaller groups are
                merged into neighbors). Default 2.
        """
        raw_scenes = await self.scene_client.get_video_scenes_with_embeddings(
            org_id, video_id,
        )

        if not raw_scenes:
            return SceneGroupsResponse(
                video_id=video_id, total_groups=0, total_scenes=0, groups=[],
            )

        similarities = compute_pairwise_similarity(raw_scenes)
        boundaries = find_group_boundaries(
            similarities,
            total_scenes=len(raw_scenes),
            threshold=threshold,
            sensitivity=sensitivity,
            min_group_size=min_group_size,
        )

        groups: list[SceneGroup] = []
        for group_index, (start, end) in enumerate(boundaries):
            group_scenes_raw = raw_scenes[start : end + 1]
            middle = len(group_scenes_raw) // 2
            representative_id = group_scenes_raw[middle]["scene_id"]

            scenes = [
                VideoScene(**_strip_embeddings(s)) for s in group_scenes_raw
            ]

            groups.append(
                SceneGroup(
                    group_index=group_index,
                    start_ms=group_scenes_raw[0]["start_ms"],
                    end_ms=group_scenes_raw[-1]["end_ms"],
                    scene_count=len(scenes),
                    representative_scene_id=representative_id,
                    scenes=scenes,
                )
            )

        logger.debug(
            "scene_groups_computed",
            video_id=video_id,
            total_scenes=len(raw_scenes),
            total_groups=len(groups),
            threshold=threshold,
        )

        return SceneGroupsResponse(
            video_id=video_id,
            total_groups=len(groups),
            total_scenes=len(raw_scenes),
            groups=groups,
        )
