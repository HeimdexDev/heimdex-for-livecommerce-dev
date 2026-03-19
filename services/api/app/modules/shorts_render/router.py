import asyncio
import logging
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.dependencies import get_scene_opensearch_client, get_shorts_render_service
from app.modules.auth.service import get_current_user
from app.modules.shorts_render.schemas import (
    RenderJobCreate,
    RenderJobListResponse,
    RenderJobResponse,
    SubtitleSuggestion,
    SubtitleSuggestions,
)
from app.modules.shorts_render.service import ShortsRenderService
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shorts/render", tags=["shorts-render"])

_RANGE_CHUNK = 2 * 1024 * 1024  # 2MB default for open-ended ranges


@router.post("", response_model=RenderJobResponse, status_code=status.HTTP_201_CREATED)
async def create_render_job(
    body: RenderJobCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    user_id = cast(UUID, user.id)
    return await service.create_render_job(org_ctx.org_id, user_id, body)


@router.get("", response_model=RenderJobListResponse)
async def list_render_jobs(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    user_id = cast(UUID, user.id)
    return await service.list_render_jobs(org_ctx.org_id, user_id, limit, offset)


@router.get("/{job_id}", response_model=RenderJobResponse)
async def get_render_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    return await service.get_render_job(org_ctx.org_id, job_id)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_render_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    await service.delete_render_job(org_ctx.org_id, job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{job_id}/download")
async def download_rendered_short(
    job_id: UUID,
    request: Request,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    """Stream the rendered MP4 from S3. Supports HTTP Range requests."""
    job = await service.get_render_job_record(org_ctx.org_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Render job not found")

    if job.status != "completed" or not job.output_s3_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Render job is not ready for download",
        )

    from app.config import get_settings
    from app.storage.s3 import S3Client

    settings = get_settings()
    s3 = S3Client(bucket=settings.drive_s3_bucket)

    try:
        loop = asyncio.get_running_loop()
        head = await loop.run_in_executor(
            None, lambda: s3._client.head_object(Bucket=s3.bucket, Key=job.output_s3_key)
        )
    except Exception:
        logger.warning("download_head_failed", extra={"key": job.output_s3_key}, exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to retrieve file from storage")

    total_size = head["ContentLength"]
    content_type = "video/mp4"
    filename = f"short_{job_id}.mp4"

    range_header = request.headers.get("range")

    if range_header:
        range_spec = range_header.strip().lower()
        if not range_spec.startswith("bytes="):
            raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE)

        range_val = range_spec[6:]
        parts = range_val.split("-", 1)
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else min(start + _RANGE_CHUNK - 1, total_size - 1)
        end = min(end, total_size - 1)

        if start >= total_size or start > end:
            raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE)

        content_length = end - start + 1
        s3_key = job.output_s3_key

        def _range_iter():
            resp = s3._client.get_object(
                Bucket=s3.bucket, Key=s3_key, Range=f"bytes={start}-{end}",
            )
            body = resp["Body"]
            try:
                while True:
                    chunk = body.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                body.close()

        return StreamingResponse(
            _range_iter(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{total_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, max-age=3600",
            },
        )

    s3_key = job.output_s3_key

    def _full_iter():
        resp = s3._client.get_object(Bucket=s3.bucket, Key=s3_key)
        body = resp["Body"]
        try:
            while True:
                chunk = body.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    return StreamingResponse(
        _full_iter(),
        media_type=content_type,
        headers={
            "Content-Length": str(total_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


_TRANSCRIPT_MAX_LEN = 50


@router.get(
    "/suggestions/{video_id}/{scene_id}",
    response_model=SubtitleSuggestions,
)
async def get_subtitle_suggestions(
    video_id: str,
    scene_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    """Return subtitle text suggestions from scene metadata."""
    doc_id = f"{org_ctx.org_id}:{scene_id}"
    scenes = await scene_opensearch.mget_scenes([doc_id])
    scene_doc = scenes.get(doc_id)

    if scene_doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene not found: {scene_id}",
        )

    seen: set[str] = set()
    suggestions: list[SubtitleSuggestion] = []

    # Product tags first
    for tag in scene_doc.get("product_tags") or []:
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            suggestions.append(SubtitleSuggestion(text=tag, source="product_tag"))

    # Keyword tags second
    for tag in scene_doc.get("keyword_tags") or []:
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            suggestions.append(SubtitleSuggestion(text=tag, source="keyword_tag"))

    # Transcript last (truncated)
    transcript = (scene_doc.get("transcript_raw") or "").strip()
    if transcript:
        truncated = transcript[:_TRANSCRIPT_MAX_LEN]
        if truncated not in seen:
            seen.add(truncated)
            suggestions.append(SubtitleSuggestion(text=truncated, source="transcript"))

    return SubtitleSuggestions(suggestions=suggestions)
