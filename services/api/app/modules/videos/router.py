"""
Video visibility router.

Endpoints:
  GET /api/videos          - List ingested videos (aggregated from scenes)
  GET /api/videos/stats    - Summary statistics
  GET /api/videos/{video_id}/scenes - Scenes for a specific video
"""
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.dependencies import (
    get_drive_file_repository,
    get_people_cluster_label_repository,
    get_people_exclude_preference_repository,
    get_reprocess_repository,
    get_scene_opensearch_client,
    get_video_service,
    get_youtube_video_repository,
)
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.drive.models import DriveConnection
from app.modules.drive.repository import DriveFileRepository
from app.modules.people.repository import (
    PeopleClusterLabelRepository,
    PeopleExcludePreferenceRepository,
)
from app.modules.people.schemas import PersonResponse
from app.modules.search.scene_client import SceneSearchClient
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User
from app.modules.videos.reprocess_repository import ReprocessRepository
from app.modules.videos.reprocess_models import SceneReprocessJob
from app.modules.videos.schemas import (
    ReprocessJobResponse,
    ReprocessScenesRequest,
    ShortsPlanRequest,
    ShortsPlanResponse,
    VideoListResponse,
    VideoPeopleResponse,
    VideoScenesResponse,
    VideoStats,
)
from app.modules.videos.service import VideoService
from app.modules.youtube.repository import YouTubeVideoRepository
from app.sqs_producer import publish_resplit_job
from heimdex_media_contracts.ingest import SourceType

logger = get_logger(__name__)
router = APIRouter(prefix="/videos", tags=["videos"])


def _to_reprocess_job_response(job: SceneReprocessJob) -> ReprocessJobResponse:
    return ReprocessJobResponse(
        job_id=str(job.id),
        video_id=job.video_id,
        status=job.status,
        scene_params=job.scene_params,
        scene_count=job.scene_count,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )


@router.get("", response_model=VideoListResponse)
async def list_videos(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    video_service: VideoService = Depends(get_video_service),
    library_id: str | None = Query(None, description="Filter by library UUID"),
    source_type: SourceType | None = Query(None, description="Filter by single source type (deprecated, use source_types)"),
    source_types: str | None = Query(None, description="Comma-separated source types: gdrive,youtube,local,removable_disk"),
    content_types: str | None = Query(None, description="Comma-separated content types: video,image"),
    date_from: str | None = Query(None, description="Filter scenes ingested on or after this ISO-8601 date"),
    date_to: str | None = Query(None, description="Filter scenes ingested on or before this ISO-8601 date"),
    sort: Literal["latest", "alpha_asc", "alpha_desc"] = Query("latest", description="Sort order: latest (by date), alpha_asc/alpha_desc (by title)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    after: str | None = Query(None, description="Cursor for next page"),
):
    """List all ingested videos for the authenticated user's org."""
    logger.debug(
        "list_videos_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        library_id=library_id,
        source_type=source_type,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
    )

    parsed_content_types = (
        [ct.strip() for ct in content_types.split(",") if ct.strip() in ("video", "image")]
        if content_types else None
    )

    valid_source_types = {"gdrive", "removable_disk", "local", "youtube"}
    parsed_source_types = (
        [st.strip() for st in source_types.split(",") if st.strip() in valid_source_types]
        if source_types else None
    )

    return await video_service.list_videos(
        org_ctx.org_id,
        library_id=library_id,
        source_type=source_type,
        source_types=parsed_source_types or None,
        content_types=parsed_content_types or None,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        page_size=page_size,
        after_cursor=after,
    )


@router.get("/stats", response_model=VideoStats)
async def video_stats(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    video_service: VideoService = Depends(get_video_service),
):
    """Get summary statistics for all ingested videos."""
    logger.debug(
        "video_stats_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
    )

    return await video_service.get_stats(org_ctx.org_id)


@router.get("/{video_id}/scenes", response_model=VideoScenesResponse)
async def video_scenes(
    video_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    video_service: VideoService = Depends(get_video_service),
    q: str | None = Query(None, description="Search query within this video's scenes (BM25 across transcript, caption, OCR, speaker)"),
    page_size: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Get all scenes for a specific video, optionally filtered by search query."""
    logger.debug(
        "video_scenes_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        video_id=video_id,
        search_query=q,
    )

    return await video_service.get_video_scenes(
        org_ctx.org_id,
        video_id,
        query=q,
        page_size=page_size,
        offset=offset,
    )


@router.get("/{video_id}/people", response_model=VideoPeopleResponse)
async def get_video_people(
    video_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    scene_opensearch: SceneSearchClient = Depends(get_scene_opensearch_client),
    people_repo: PeopleClusterLabelRepository = Depends(get_people_cluster_label_repository),
    exclude_repo: PeopleExcludePreferenceRepository = Depends(get_people_exclude_preference_repository),
):
    """List people (face clusters) appearing in a specific video."""
    settings = get_settings()
    if not settings.people_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="People feature is not enabled",
        )

    org_id_str = str(org_ctx.org_id)
    user_id = cast(UUID, user.id)

    people_buckets = await scene_opensearch.get_people_by_video(org_id_str, video_id)
    if not people_buckets:
        return VideoPeopleResponse(video_id=video_id, people=[], total=0)

    labels = await people_repo.list_by_org(org_ctx.org_id)
    label_map = {entry.person_cluster_id: entry.label for entry in labels}

    excluded_ids = set(await exclude_repo.list_by_user(org_ctx.org_id, user_id))

    cluster_ids = [b["person_cluster_id"] for b in people_buckets]
    rep_scenes = await scene_opensearch.get_representative_scenes_for_people(
        org_id_str, cluster_ids,
    )

    people: list[PersonResponse] = []
    for bucket in people_buckets:
        cluster_id = bucket["person_cluster_id"]
        person = PersonResponse(
            person_cluster_id=cluster_id,
            label=label_map.get(cluster_id),
            face_count=bucket["face_count"],
            is_excluded=cluster_id in excluded_ids,
        )
        scene_info = rep_scenes.get(cluster_id)
        if scene_info:
            person.representative_video_id = scene_info["video_id"]
            person.representative_scene_id = scene_info["scene_id"]
            person.last_seen_scene_time = scene_info.get("ingest_time")
        people.append(person)

    return VideoPeopleResponse(video_id=video_id, people=people, total=len(people))


@router.post("/{video_id}/shorts/plan", response_model=ShortsPlanResponse)
async def generate_shorts_plan(
    video_id: str,
    request: ShortsPlanRequest = ShortsPlanRequest(),
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    video_service: VideoService = Depends(get_video_service),
):
    logger.debug(
        "shorts_plan_request",
        user_id=str(user.id),
        org_id=str(org_ctx.org_id),
        video_id=video_id,
        target_count=request.target_count,
    )

    return await video_service.generate_shorts_plan(
        org_ctx.org_id,
        video_id,
        target_count=request.target_count,
        min_duration_ms=request.min_duration_ms,
        max_duration_ms=request.max_duration_ms,
        weights=request.weights,
    )


@router.post("/{video_id}/reprocess", response_model=ReprocessJobResponse)
async def reprocess_video_scenes(
    video_id: str,
    request: ReprocessScenesRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    repo: ReprocessRepository = Depends(get_reprocess_repository),
    drive_repo: DriveFileRepository = Depends(get_drive_file_repository),
    yt_repo: YouTubeVideoRepository = Depends(get_youtube_video_repository),
):
    _ = user
    if request.min_scene_duration_ms >= request.max_scene_duration_ms:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_scene_duration_ms must be less than max_scene_duration_ms",
        )

    active = await repo.get_active_for_video(org_ctx.org_id, video_id)
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reprocess job already active for this video",
        )

    source_type: str
    proxy_s3_key: str | None = None
    keyframe_s3_prefix: str = ""
    audio_s3_key: str = ""
    library_id: str | None = None
    video_title: str = video_id

    if video_id.startswith("gd_"):
        source_type = "gdrive"
        drive_file = await drive_repo.get_by_video_id(org_ctx.org_id, video_id)
        if drive_file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found",
            )
        proxy_s3_key = drive_file.proxy_s3_key
        keyframe_s3_prefix = drive_file.keyframe_s3_prefix or ""
        audio_s3_key = drive_file.audio_s3_key or ""
        video_title = drive_file.file_name or video_id
        connection = await db.get(DriveConnection, drive_file.connection_id)
        if connection is not None:
            library_id = str(connection.library_id)
    elif video_id.startswith("yt_"):
        source_type = "youtube"
        yt_video = await yt_repo.get_by_video_id(org_ctx.org_id, video_id)
        if yt_video is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Video not found",
            )
        proxy_s3_key = getattr(yt_video, "proxy_s3_key", None)
        keyframe_s3_prefix = getattr(yt_video, "keyframe_s3_prefix", "") or ""
        audio_s3_key = getattr(yt_video, "audio_s3_key", "") or ""
        library_id = getattr(yt_video, "library_id", None)
        video_title = getattr(yt_video, "title", video_id) or video_id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported video_id prefix",
        )

    if not proxy_s3_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video must be transcoded before reprocessing",
        )

    if not library_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Video library not found",
        )

    scene_params = {
        "min_scene_duration_ms": request.min_scene_duration_ms,
        "max_scene_duration_ms": request.max_scene_duration_ms,
        "threshold": request.threshold,
        "split_preset": request.split_preset,
        "use_speech": request.use_speech,
    }

    job = await repo.create(
        org_id=org_ctx.org_id,
        video_id=video_id,
        source_type=source_type,
        scene_params=cast(dict[str, object], scene_params),
        proxy_s3_key=proxy_s3_key,
    )

    publish_resplit_job(
        job_id=cast(UUID, job.id),
        org_id=org_ctx.org_id,
        video_id=video_id,
        source_type=source_type,
        proxy_s3_key=proxy_s3_key,
        keyframe_s3_prefix=keyframe_s3_prefix,
        audio_s3_key=audio_s3_key,
        library_id=library_id,
        video_title=video_title,
        scene_params=scene_params,
    )

    return _to_reprocess_job_response(job)


@router.get("/{video_id}/reprocess", response_model=ReprocessJobResponse | None)
async def get_reprocess_status(
    video_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    repo: ReprocessRepository = Depends(get_reprocess_repository),
):
    _ = user
    job = await repo.get_latest_for_video(org_ctx.org_id, video_id)
    if job is None:
        return None
    return _to_reprocess_job_response(job)
