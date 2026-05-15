from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import (
    get_library_repository,
    get_youtube_channel_repository,
    get_youtube_video_repository,
)
from app.modules.auth.service import get_current_user
from app.modules.libraries.repository import LibraryRepository
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

from .models import YouTubeChannel, YouTubeVideo
from .repository import YouTubeChannelRepository, YouTubeVideoRepository
from .schemas import (
    ChannelListResponse,
    ChannelResponse,
    RegisterChannelRequest,
    SyncTriggerResponse,
    YouTubeVideoListResponse,
    YouTubeVideoResponse,
)
from .service import YouTubeService

router = APIRouter(prefix="/youtube", tags=["youtube"])


def _to_channel_response(channel: YouTubeChannel) -> ChannelResponse:
    return ChannelResponse(
        id=cast(UUID, channel.id),
        channel_id=channel.channel_id,
        channel_url=channel.channel_url,
        channel_name=channel.channel_name,
        thumbnail_url=channel.thumbnail_url,
        video_count=channel.video_count,
        last_synced_at=channel.last_synced_at,
        sync_enabled=channel.sync_enabled,
        created_at=channel.created_at,
    )


def _to_video_response(video: YouTubeVideo) -> YouTubeVideoResponse:
    return YouTubeVideoResponse(
        id=cast(UUID, video.id),
        youtube_video_id=video.youtube_video_id,
        video_id=video.video_id,
        title=video.title,
        duration_seconds=video.duration_seconds,
        publish_date=video.publish_date,
        processing_status=video.processing_status,
        has_subtitles=video.has_subtitles,
        enrichment_status=video.enrichment_status,
        created_at=video.created_at,
    )


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


@router.post("/channels", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def register_channel(
    body: RegisterChannelRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
    library_repo: Annotated[LibraryRepository, Depends(get_library_repository)],
):
    service = _get_service(channel_repo, video_repo, library_repo)
    try:
        channel = await service.register_channel(
            org_id=org_ctx.org_id,
            channel_url=body.channel_url,
            channel_name=body.channel_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_channel_response(channel)


@router.get("/channels", response_model=ChannelListResponse)
async def list_channels(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
):
    channels = await channel_repo.list_by_org(org_ctx.org_id)
    channel_responses = [_to_channel_response(channel) for channel in channels]
    return ChannelListResponse(channels=channel_responses, total=len(channel_responses))


@router.get("/channels/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
):
    channel = await channel_repo.get_by_id(channel_id, org_ctx.org_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return _to_channel_response(channel)


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
):
    channel = await channel_repo.get_by_id(channel_id, org_ctx.org_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await channel_repo.delete(channel)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/channels/{channel_id}/videos", response_model=YouTubeVideoListResponse)
async def list_channel_videos(
    channel_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
    video_repo: Annotated[YouTubeVideoRepository, Depends(get_youtube_video_repository)],
):
    channel = await channel_repo.get_by_id(channel_id, org_ctx.org_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    videos = await video_repo.list_by_channel(org_id=org_ctx.org_id, channel_id=channel_id)
    video_responses = [_to_video_response(video) for video in videos]
    return YouTubeVideoListResponse(videos=video_responses, total=len(video_responses))


@router.post(
    "/channels/{channel_id}/sync",
    response_model=SyncTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_manual_sync(
    channel_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    channel_repo: Annotated[YouTubeChannelRepository, Depends(get_youtube_channel_repository)],
):
    channel = await channel_repo.get_by_id(channel_id, org_ctx.org_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    return SyncTriggerResponse(status="accepted")
