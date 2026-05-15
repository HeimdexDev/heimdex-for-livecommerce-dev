import asyncio
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.dependencies import (
    get_library_repository,
    verify_internal_token,
    get_youtube_channel_repository,
    get_youtube_video_repository,
)
from app.modules.libraries.repository import LibraryRepository
from app.sqs_producer import (
    publish_enrichment_jobs,
    publish_scene_enrichment_jobs,
    publish_youtube_transcode_job,
)

from .models import YouTubeVideo
from .repository import YouTubeChannelRepository, YouTubeVideoRepository, _is_enrichment_complete
from .schemas import (
    ChannelListResponse,
    CreateYouTubeVideoRequest,
    KnownYouTubeVideoIdsResponse,
    SyncCompleteRequest,
    TriggerTranscodeRequest,
    UpdateYouTubeVideoStatusRequest,
    YouTubeVideoResponse,
    YouTubeVideoListResponse,
)
from .router import _to_channel_response, _to_video_response
from .service import YouTubeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/youtube", tags=["internal-youtube"])


async def _publish_scene_jobs_in_background(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> None:
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: publish_scene_enrichment_jobs(
                file_id=file_id,
                org_id=org_id,
                video_id=video_id,
                scenes=scenes,
            ),
        )
        logger.info(
            "youtube_scene_enrichment_jobs_published",
            extra={"video_id": video_id, "scene_count": len(scenes)},
        )
    except Exception:
        logger.warning(
            "youtube_scene_enrichment_jobs_failed",
            extra={"video_id": video_id},
            exc_info=True,
        )


def _parse_org_id(x_heimdex_org_id: str) -> UUID:
    try:
        return UUID(x_heimdex_org_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        ) from exc


def _get_service(
    channel_repo: YouTubeChannelRepository,
    video_repo: YouTubeVideoRepository,
    library_repo: LibraryRepository,
) -> YouTubeService:
    return YouTubeService(
        channel_repo=channel_repo,
        video_repo=video_repo,
        library_repo=library_repo,
    )


async def _to_internal_video_dict(
    video: YouTubeVideo,
    channel_repo: YouTubeChannelRepository,
) -> YouTubeVideoResponse:
    channel = await channel_repo.get_by_id(video.channel_id, video.org_id)
    return YouTubeVideoResponse(
        id=video.id,
        org_id=video.org_id,
        channel_id=video.channel_id,
        channel_external_id=channel.channel_id if channel is not None else None,
        youtube_video_id=video.youtube_video_id,
        video_id=video.video_id,
        title=video.title,
        duration_seconds=video.duration_seconds,
        publish_date=video.publish_date,
        processing_status=video.processing_status,
        has_subtitles=video.has_subtitles,
        enrichment_status=video.enrichment_status,
        original_deleted=video.original_deleted,
        all_enrichment_complete=_is_enrichment_complete(video.enrichment_status),
        created_at=video.created_at,
    )


@router.get("/channels", response_model=ChannelListResponse)
async def list_enabled_channels(
    x_heimdex_org_id: Annotated[str, Header(..., alias="X-Heimdex-Org-Id")],
    _token: Annotated[str, Depends(verify_internal_token)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
):
    org_id = _parse_org_id(x_heimdex_org_id)
    channels = await channel_repo.list_by_org(org_id, sync_enabled=True)
    items = [_to_channel_response(channel) for channel in channels]
    return ChannelListResponse(channels=items, total=len(items))


@router.get("/channels/{channel_id}/video_ids", response_model=KnownYouTubeVideoIdsResponse)
async def list_known_video_ids(
    channel_id: UUID,
    _token: Annotated[str, Depends(verify_internal_token)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    x_heimdex_org_id: Annotated[str | None, Header(alias="X-Heimdex-Org-Id")] = None,
):
    from app.lib.internal_auth import resolve_resource_with_org

    channel, org_id = await resolve_resource_with_org(
        resource_id=channel_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=channel_repo.get_by_id_resource_scoped,
        not_found_detail="Channel not found",
    )
    video_ids = await video_repo.list_known_youtube_video_ids(org_id=org_id, channel_id=channel_id)
    return KnownYouTubeVideoIdsResponse(video_ids=video_ids, total=len(video_ids))


@router.post("/channels/{channel_id}/videos", response_model=YouTubeVideoResponse, status_code=status.HTTP_201_CREATED)
async def create_video(
    channel_id: UUID,
    body: CreateYouTubeVideoRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repository)],
    x_heimdex_org_id: Annotated[str | None, Header(alias="X-Heimdex-Org-Id")] = None,
):
    from app.lib.internal_auth import resolve_resource_with_org

    channel, org_id = await resolve_resource_with_org(
        resource_id=channel_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=channel_repo.get_by_id_resource_scoped,
        not_found_detail="Channel not found",
    )

    service = _get_service(channel_repo, video_repo, library_repo)
    video = await service.create_video_record(org_id=org_id, channel=channel, request=body)
    return _to_video_response(video)


@router.patch("/channels/{channel_id}/sync-complete")
async def mark_channel_synced(
    channel_id: UUID,
    body: SyncCompleteRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    x_heimdex_org_id: Annotated[str | None, Header(alias="X-Heimdex-Org-Id")] = None,
):
    from app.lib.internal_auth import resolve_resource_with_org

    channel, _org_id = await resolve_resource_with_org(
        resource_id=channel_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=channel_repo.get_by_id_resource_scoped,
        not_found_detail="Channel not found",
    )

    await channel_repo.update_last_synced_at(channel)
    await channel_repo.set_video_count(channel, body.discovered_count)
    return {"ok": True}


@router.patch("/videos/{video_id}/status", response_model=YouTubeVideoResponse)
async def update_video_status(
    video_id: UUID,
    body: UpdateYouTubeVideoStatusRequest,
    _token: Annotated[str, Depends(verify_internal_token)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repository)],
    x_heimdex_org_id: Annotated[str | None, Header(alias="X-Heimdex-Org-Id")] = None,
):
    from app.lib.internal_auth import resolve_resource_with_org

    video, org_id = await resolve_resource_with_org(
        resource_id=video_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=video_repo.get_by_id_resource_scoped,
        not_found_detail="Video not found",
    )

    service = _get_service(channel_repo, video_repo, library_repo)
    service.inject_subtitle_status(
        video=video,
        subtitle_language=body.subtitle_language,
        has_subtitles=body.has_subtitles,
    )
    await video_repo.update_status(
        video=video,
        processing_status=body.processing_status,
        subtitle_language=video.subtitle_language,
        has_subtitles=video.has_subtitles,
        enrichment_status=body.enrichment_status or video.enrichment_status,
        original_deleted=body.original_deleted,
    )

    # Publish enrichment SQS jobs when transcode finishes (mirrors Drive handler).
    if body.processing_status == "indexed":
        _eff_keyframe = body.keyframe_s3_prefix
        _eff_audio = body.audio_s3_key

        # v1: per-video enrichment for STT, OCR, face
        if _eff_keyframe or _eff_audio:
            publish_enrichment_jobs(
                file_id=video.id,
                org_id=org_id,
                video_id=video.video_id,
                keyframe_s3_prefix=_eff_keyframe,
                audio_s3_key=_eff_audio,
            )

        # v2: per-scene enrichment for caption + visual-embed
        _scene_count = body.scene_count or 0
        if _scene_count > 0 and _eff_keyframe:
            _vid = video.video_id
            scenes_for_publish = [
                {
                    "scene_id": f"{_vid}_scene_{i:03d}",
                    "scene_index": i,
                    "keyframe_s3_key": f"{_eff_keyframe}{_vid}_scene_{i:03d}.jpg",
                }
                for i in range(_scene_count)
            ]
            asyncio.create_task(
                _publish_scene_jobs_in_background(
                    file_id=video.id,
                    org_id=org_id,
                    video_id=_vid,
                    scenes=scenes_for_publish,
                )
            )

    return _to_video_response(video)


@router.post("/transcode")
async def trigger_transcode(
    body: TriggerTranscodeRequest,
    x_heimdex_org_id: Annotated[str, Header(..., alias="X-Heimdex-Org-Id")],
    _token: Annotated[str, Depends(verify_internal_token)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repository)],
):
    org_id = _parse_org_id(x_heimdex_org_id)
    body_org_id = _parse_org_id(body.org_id)
    if body_org_id != org_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="org_id mismatch")

    video = await video_repo.get_by_video_id(org_id, body.video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video not found")

    channel = await channel_repo.get_by_id(video.channel_id, org_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")

    service = _get_service(channel_repo, video_repo, library_repo)
    library = await service.get_or_create_reference_library(org_id)

    publish_youtube_transcode_job(
        file_id=video.id,
        org_id=org_id,
        video_id=video.video_id,
        youtube_video_id=body.youtube_video_id,
        file_name=video.title,
        original_s3_key=body.original_s3_key,
        original_size_bytes=body.original_size_bytes,
        library_id=library.id,
        web_view_link=f"https://www.youtube.com/watch?v={video.youtube_video_id}",
    )

    await video_repo.update_status(
        video=video,
        processing_status="transcoding",
        has_subtitles=body.has_subtitles,
    )
    return {"ok": True, "message_sent": True}


@router.get("/videos/pending", response_model=YouTubeVideoListResponse)
async def list_pending_videos(
    x_heimdex_org_id: Annotated[str, Header(..., alias="X-Heimdex-Org-Id")],
    _token: Annotated[str, Depends(verify_internal_token)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    limit: int = 5,
):
    org_id = _parse_org_id(x_heimdex_org_id)
    videos = await video_repo.list_pending(org_id=org_id, limit=max(1, min(limit, 100)))
    items = [await _to_internal_video_dict(video, channel_repo) for video in videos]
    return YouTubeVideoListResponse(videos=items, total=len(items))


@router.get("/videos/cleanup-candidates", response_model=YouTubeVideoListResponse)
async def list_cleanup_candidates(
    x_heimdex_org_id: Annotated[str, Header(..., alias="X-Heimdex-Org-Id")],
    _token: Annotated[str, Depends(verify_internal_token)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
):
    org_id = _parse_org_id(x_heimdex_org_id)
    videos = await video_repo.list_cleanup_candidates(org_id=org_id)
    items = [await _to_internal_video_dict(video, channel_repo) for video in videos]
    return YouTubeVideoListResponse(videos=items, total=len(items))


@router.patch("/videos/{video_id}/mark-deleted", response_model=YouTubeVideoResponse)
async def mark_original_deleted(
    video_id: UUID,
    _token: Annotated[str, Depends(verify_internal_token)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    x_heimdex_org_id: Annotated[str | None, Header(alias="X-Heimdex-Org-Id")] = None,
):
    from app.lib.internal_auth import resolve_resource_with_org

    video, _org_id = await resolve_resource_with_org(
        resource_id=video_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=video_repo.get_by_id_resource_scoped,
        not_found_detail="Video not found",
    )
    await video_repo.mark_original_deleted(video)
    return _to_video_response(video)
