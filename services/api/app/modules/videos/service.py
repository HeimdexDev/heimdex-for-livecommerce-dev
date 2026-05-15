"""
Video visibility service.

Thin orchestration layer: delegates to SceneSearchClient for aggregation,
enriches with library names from Postgres.
"""
import base64
import json
from typing import TypedDict, cast
from uuid import UUID

from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.scorer import select_shorts_candidates
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.modules.libraries.repository import LibraryRepository
from app.modules.search.scene_client import SceneSearchClient
from app.modules.drive.repository import DriveFileRepository
from app.modules.videos.schemas import (
    ShortsCandidateResponse,
    ShortsPlanResponse,
    VideoFacetItem,
    VideoFacets,
    VideoListResponse,
    VideoScene,
    VideoScenesResponse,
    VideoStats,
    VideoSummary,
)

logger = get_logger(__name__)


class _ScenePayload(TypedDict, total=False):
    scene_id: str
    start_ms: int
    end_ms: int
    keyframe_timestamp_ms: int
    transcript_raw: str
    transcript_char_count: int
    speech_segment_count: int
    people_cluster_ids: list[str]
    keyword_tags: list[str]
    product_tags: list[str]
    product_entities: list[str]
    ocr_text_raw: str
    ocr_char_count: int


class VideoService:
    """Derives video-level views from OpenSearch scene aggregations."""

    def __init__(self, session: AsyncSession, scene_client: SceneSearchClient):
        self.session = session
        self.scene_client = scene_client

    async def list_videos(
        self,
        org_id: UUID,
        *,
        library_id: str | None = None,
        source_type: str | None = None,
        source_types: list[str] | None = None,
        content_types: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "latest",
        page_size: int = 20,
        after_cursor: str | None = None,
    ) -> VideoListResponse:
        """List ingested videos for an org via OpenSearch aggregation."""
        offset = 0
        if after_cursor:
            try:
                cursor_data = json.loads(base64.urlsafe_b64decode(after_cursor))
                offset = cursor_data.get("offset", 0) if isinstance(cursor_data, dict) else 0
            except Exception:
                logger.warning("invalid_video_cursor", cursor=after_cursor)

        result = await self.scene_client.aggregate_videos(
            str(org_id),
            library_id=library_id,
            source_type=source_type,
            source_types=source_types,
            content_types=content_types,
            date_from=date_from,
            date_to=date_to,
            sort=sort,
            page_size=page_size,
            offset=offset,
        )

        # Enrich with library names
        library_repo = LibraryRepository(self.session)
        libraries = await library_repo.list_by_org(org_id)
        library_map = {str(lib.id): lib.name for lib in libraries}

        videos = [
            VideoSummary(
                 video_id=v["video_id"],
                 video_title=v["video_title"],
                 library_id=v["library_id"],
                 library_name=library_map.get(v["library_id"] or "", "Unknown"),
                 source_type=v["source_type"],
                 scene_count=v["scene_count"],
                 first_scene_start_ms=v["first_scene_start_ms"],
                 last_scene_end_ms=v["last_scene_end_ms"],
                 earliest_ingest_time=v["earliest_ingest_time"],
                 latest_ingest_time=v["latest_ingest_time"],
                 capture_time=v.get("capture_time"),
                 first_scene_keyframe_ms=v.get("first_scene_keyframe_ms", 0),
                  keyword_tags=v["keyword_tags"],
                  product_tags=v["product_tags"],
                  people_count=v["people_count"],
                  required_drive_nickname=v["required_drive_nickname"],
                  source_path=v.get("source_path"),
                  web_view_link=v.get("web_view_link"),
                  content_type=v.get("content_type", "video"),
              )
              for v in result["videos"]
          ]

        # Backfill web_view_link from Postgres for videos missing it in OpenSearch
        missing_drive_ids = [v.video_id for v in videos if not v.web_view_link and v.video_id.startswith("gd_")]
        if missing_drive_ids:
            drive_repo = DriveFileRepository(self.session)
            link_map = await drive_repo.get_web_view_links(org_id, missing_drive_ids)
            for v in videos:
                if not v.web_view_link and v.video_id in link_map:
                    v.web_view_link = link_map[v.video_id]

        missing_yt_ids = [v.video_id for v in videos if not v.web_view_link and v.video_id.startswith("yt_")]
        if missing_yt_ids:
            from app.modules.youtube.repository import YouTubeVideoRepository
            yt_repo = YouTubeVideoRepository(self.session)
            yt_link_map = await yt_repo.get_web_view_links(org_id, missing_yt_ids)
            for v in videos:
                if not v.web_view_link and v.video_id in yt_link_map:
                    v.web_view_link = yt_link_map[v.video_id]

        # Encode next cursor
        next_cursor = None
        if result["next_cursor"]:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(result["next_cursor"]).encode()
            ).decode()

        facets = VideoFacets(
            libraries=[
                VideoFacetItem(
                    id=bucket["key"],
                    name=library_map.get(bucket["key"]),
                    count=bucket["doc_count"],
                )
                for bucket in result["facets"]["libraries"]
            ],
            source_types=[
                VideoFacetItem(
                    id=bucket["key"],
                    name=bucket["key"],
                    count=bucket["doc_count"],
                )
                for bucket in result["facets"]["source_types"]
            ],
        )

        logger.info(
            "videos_listed",
            org_id=str(org_id),
            video_count=len(videos),
            total=result["total"],
        )

        return VideoListResponse(
            videos=videos,
            total=result["total"],
            next_cursor=next_cursor,
            facets=facets,
        )

    async def get_video_scenes(
        self,
        org_id: UUID,
        video_id: str,
        *,
        query: str | None = None,
        page_size: int = 50,
        offset: int = 0,
    ) -> VideoScenesResponse:
        result = await self.scene_client.get_video_scenes(
            str(org_id),
            video_id,
            query=query,
            page_size=page_size,
            offset=offset,
        )

        scenes = [VideoScene(**s) for s in result["scenes"]]

        # Merge user overrides from PostgreSQL (safety net for dual-write)
        from app.modules.scene_overrides.repository import SceneOverrideRepository
        import json as _json
        override_repo = SceneOverrideRepository(self.session)
        overrides = await override_repo.get_by_video(org_id, video_id)
        if overrides:
            override_map = {o.scene_id: o for o in overrides}
            for scene in scenes:
                ov = override_map.get(scene.scene_id)
                if ov is None:
                    continue
                fields = set(ov.overridden_fields.split(",")) if ov.overridden_fields else set()
                if "scene_caption" in fields and ov.scene_caption is not None:
                    scene.scene_caption = ov.scene_caption
                if "transcript_raw" in fields and ov.transcript_raw is not None:
                    scene.transcript_raw = ov.transcript_raw
                if "speaker_transcript" in fields and ov.speaker_transcript is not None:
                    scene.speaker_transcript = ov.speaker_transcript
                if "ai_tags" in fields and ov.ai_tags_json is not None:
                    scene.ai_tags = _json.loads(ov.ai_tags_json)
                scene.is_edited = True
                scene.edited_fields = sorted(fields)

        library_name: str | None = None
        lib_id = result.get("library_id")
        if lib_id:
            library_repo = LibraryRepository(self.session)
            libraries = await library_repo.list_by_org(org_id)
            library_map = {str(lib.id): lib.name for lib in libraries}
            library_name = library_map.get(lib_id)

        # Backfill web_view_link from Postgres if missing in OpenSearch
        web_view_link = result.get("web_view_link")
        if not web_view_link and video_id.startswith("gd_"):
            drive_repo = DriveFileRepository(self.session)
            link_map = await drive_repo.get_web_view_links(org_id, [video_id])
            web_view_link = link_map.get(video_id)
        if not web_view_link and video_id.startswith("yt_"):
            from app.modules.youtube.repository import YouTubeVideoRepository
            yt_repo = YouTubeVideoRepository(self.session)
            yt_link_map = await yt_repo.get_web_view_links(org_id, [video_id])
            web_view_link = yt_link_map.get(video_id)

        return VideoScenesResponse(
            video_id=video_id,
            video_title=result.get("video_title"),
            source_type=result.get("source_type"),
            source_path=result.get("source_path"),
            library_name=library_name,
            capture_time=result.get("capture_time"),
            earliest_ingest_time=result.get("earliest_ingest_time"),
            web_view_link=web_view_link,
            scenes=scenes,
            total=result["total"],
        )

    async def get_stats(self, org_id: UUID) -> VideoStats:
        """Get summary statistics for all ingested videos."""
        result = await self.scene_client.get_video_stats(str(org_id))
        return VideoStats(**result)

    async def generate_shorts_plan(
        self,
        org_id: UUID,
        video_id: str,
        *,
        target_count: int = 15,
        min_duration_ms: int = 30_000,
        max_duration_ms: int = 45_000,
        weights: dict[str, float] | None = None,
    ) -> ShortsPlanResponse:
        all_scenes_raw: list[_ScenePayload] = []
        offset = 0
        page_size = 200

        while True:
            result = await self.scene_client.get_video_scenes(
                str(org_id),
                video_id,
                page_size=page_size,
                offset=offset,
            )
            scenes_raw = result.get("scenes", [])
            if isinstance(scenes_raw, list):
                scenes = [
                    cast(_ScenePayload, cast(object, scene_item))
                    for scene_item in scenes_raw
                    if isinstance(scene_item, dict)
                ]
            else:
                scenes = []
            all_scenes_raw.extend(scenes)
            total_raw = result.get("total", 0)
            total = total_raw if isinstance(total_raw, int) else 0
            if len(all_scenes_raw) >= total or not scenes:
                break
            offset += page_size

        video_title = None

        scene_docs: list[SceneDocument] = []
        for scene in all_scenes_raw:
            raw_scene_id = scene.get("scene_id")
            scene_id = raw_scene_id if isinstance(raw_scene_id, str) else ""
            if "_scene_" in scene_id:
                _, _, index_part = scene_id.rpartition("_scene_")
                scene_index = int(index_part) if index_part.isdigit() else 0
            else:
                scene_index = 0

            raw_start_ms = scene.get("start_ms")
            start_ms = raw_start_ms if isinstance(raw_start_ms, int) else 0
            raw_end_ms = scene.get("end_ms")
            end_ms = raw_end_ms if isinstance(raw_end_ms, int) else 0
            raw_keyframe_ms = scene.get("keyframe_timestamp_ms")
            keyframe_timestamp_ms = raw_keyframe_ms if isinstance(raw_keyframe_ms, int) else 0

            raw_transcript = scene.get("transcript_raw")
            transcript_raw = raw_transcript if isinstance(raw_transcript, str) else ""
            raw_transcript_char_count = scene.get("transcript_char_count")
            transcript_char_count = (
                raw_transcript_char_count if isinstance(raw_transcript_char_count, int) else 0
            )
            raw_speech_segment_count = scene.get("speech_segment_count")
            speech_segment_count = (
                raw_speech_segment_count if isinstance(raw_speech_segment_count, int) else 0
            )

            raw_people_cluster_ids = scene.get("people_cluster_ids")
            people_cluster_ids = (
                [item for item in raw_people_cluster_ids if isinstance(item, str)]
                if isinstance(raw_people_cluster_ids, list)
                else []
            )
            raw_keyword_tags = scene.get("keyword_tags")
            keyword_tags = (
                [item for item in raw_keyword_tags if isinstance(item, str)]
                if isinstance(raw_keyword_tags, list)
                else []
            )
            raw_product_tags = scene.get("product_tags")
            product_tags = (
                [item for item in raw_product_tags if isinstance(item, str)]
                if isinstance(raw_product_tags, list)
                else []
            )
            raw_product_entities = scene.get("product_entities")
            product_entities = (
                [item for item in raw_product_entities if isinstance(item, str)]
                if isinstance(raw_product_entities, list)
                else []
            )

            raw_ocr_text = scene.get("ocr_text_raw")
            ocr_text_raw = raw_ocr_text if isinstance(raw_ocr_text, str) else ""
            raw_ocr_char_count = scene.get("ocr_char_count")
            ocr_char_count = raw_ocr_char_count if isinstance(raw_ocr_char_count, int) else 0

            scene_docs.append(
                SceneDocument(
                    scene_id=scene_id,
                    video_id=video_id,
                    index=scene_index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    keyframe_timestamp_ms=keyframe_timestamp_ms,
                    transcript_raw=transcript_raw,
                    transcript_char_count=transcript_char_count,
                    speech_segment_count=speech_segment_count,
                    people_cluster_ids=people_cluster_ids,
                    keyword_tags=keyword_tags,
                    product_tags=product_tags,
                    product_entities=product_entities,
                    ocr_text_raw=ocr_text_raw,
                    ocr_char_count=ocr_char_count,
                )
            )

        eligible_count = sum(
            1
            for scene_doc in scene_docs
            if min_duration_ms <= scene_doc.duration_ms <= max_duration_ms
        )

        candidates = select_shorts_candidates(
            scene_docs,
            target_count=target_count,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            weights=weights,
        )

        logger.info(
            "shorts_plan_generated",
            org_id=str(org_id),
            video_id=video_id,
            total_scenes=len(scene_docs),
            eligible_scenes=eligible_count,
            candidates_returned=len(candidates),
        )

        return ShortsPlanResponse(
            video_id=video_id,
            video_title=video_title,
            total_scenes=len(scene_docs),
            eligible_scenes=eligible_count,
            candidates=[
                ShortsCandidateResponse(
                    candidate_id=candidate.candidate_id,
                    video_id=candidate.video_id,
                    scene_ids=candidate.scene_ids,
                    start_ms=candidate.start_ms,
                    end_ms=candidate.end_ms,
                    title_suggestion=candidate.title_suggestion,
                    reason=candidate.reason,
                    score=candidate.score,
                    tags=candidate.tags,
                    product_refs=candidate.product_refs,
                    people_refs=candidate.people_refs,
                    transcript_snippet=candidate.transcript_snippet,
                )
                for candidate in candidates
            ],
        )
