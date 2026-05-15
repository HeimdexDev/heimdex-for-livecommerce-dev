"""Highlight reel service — orchestrates port, domain, and composition building.

Does NOT import from shorts_render internals. The router handles wiring
the resulting CompositionSpec to the render service.
"""
from __future__ import annotations

from uuid import UUID

from app.logging_config import get_logger
from app.modules.highlight_reel.domain import HighlightRequest, build_highlight_plan
from app.modules.highlight_reel.port import SceneDataPort
from app.modules.highlight_reel.schemas import (
    HighlightClipPreview,
    HighlightReelPreviewResponse,
)

logger = get_logger(__name__)


class HighlightReelService:
    def __init__(self, scene_data: SceneDataPort) -> None:
        self._scene_data = scene_data

    async def generate_preview(
        self,
        org_id: str,
        user_id: UUID,
        person_cluster_id: str,
        target_duration_s: int,
    ) -> HighlightReelPreviewResponse:
        org_uuid = UUID(org_id)

        scenes = await self._scene_data.get_person_scenes(org_id, person_cluster_id)
        excluded = await self._scene_data.get_excluded_video_ids(org_uuid, user_id, person_cluster_id)
        video_titles = await self._scene_data.get_video_titles(org_id, person_cluster_id)

        logger.info(
            "highlight_reel_preview_requested",
            org_id=org_id,
            person_cluster_id=person_cluster_id,
            target_duration_s=target_duration_s,
            total_scenes=len(scenes),
            excluded_video_count=len(excluded),
        )

        plan = build_highlight_plan(
            scenes,
            HighlightRequest(
                target_duration_ms=target_duration_s * 1000,
                excluded_video_ids=frozenset(excluded),
            ),
        )

        clips = [
            HighlightClipPreview(
                video_id=clip.video_id,
                video_title=video_titles.get(clip.video_id),
                scene_id=clip.scene_id,
                start_ms=clip.start_ms,
                end_ms=clip.end_ms,
                timeline_start_ms=clip.timeline_start_ms,
                duration_ms=clip.duration_ms,
                run_scene_count=clip.source_run_scene_count,
            )
            for clip in plan.clips
        ]

        return HighlightReelPreviewResponse(
            person_cluster_id=person_cluster_id,
            clips=clips,
            total_duration_ms=plan.total_duration_ms,
            videos_used=plan.videos_used,
            videos_available=plan.videos_available,
            videos_excluded=len(excluded),
        )

    @staticmethod
    def build_composition_dict(clips: list[HighlightClipPreview]) -> dict:
        """Convert preview clips to a CompositionSpec-compatible dict.

        Returns a plain dict (not a CompositionSpec object) to avoid
        importing heimdex-media-contracts in this module. The router
        passes this dict to the render service which constructs the
        actual CompositionSpec.
        """
        scene_clips = []
        timeline_cursor = 0
        for clip in clips:
            scene_clips.append({
                "scene_id": clip.scene_id,
                "video_id": clip.video_id,
                "source_type": "gdrive",
                "start_ms": clip.start_ms,
                "end_ms": clip.end_ms,
                "timeline_start_ms": timeline_cursor,
                "volume": 1.0,
                "crop_x": 0.0,
                "crop_y": 0.0,
                "crop_w": 1.0,
                "crop_h": 1.0,
            })
            timeline_cursor += clip.duration_ms

        return {
            "output": {
                "width": 1280,
                "height": 720,
                "fps": 30,
                "format": "mp4",
                "background_color": "#000000",
            },
            "scene_clips": scene_clips,
            "subtitles": [],
            "transitions": [],
            "title": None,
            "version": 1,
        }
