import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.dependencies import get_drive_file_repository, verify_internal_token
from app.modules.drive.repository import DriveFileRepository
from app.modules.shorts_render.repository import ShortsRenderJobRepository
from app.modules.shorts_render.schemas import RenderStatusUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/shorts-render", tags=["internal-shorts-render"])


def _parse_org_id(x_heimdex_org_id: str) -> UUID:
    try:
        return UUID(x_heimdex_org_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        ) from exc


class MediaSourceResponse(BaseModel):
    video_id: str
    source_type: str
    proxy_s3_key: str | None = None
    google_file_id: str | None = None


@router.put("/{job_id}/status")
async def update_render_status(
    job_id: UUID,
    payload: RenderStatusUpdate,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Called by render worker to report job completion/failure."""
    repo = ShortsRenderJobRepository(db)

    kwargs = {}
    for field in ("output_s3_key", "output_duration_ms", "output_size_bytes", "render_time_ms", "error"):
        value = getattr(payload, field)
        if value is not None:
            kwargs[field] = value

    job = await repo.update_status(job_id, payload.status, **kwargs)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Render job not found",
        )

    if payload.status == "completed":
        logger.info(
            "render_job_completed",
            extra={
                "job_id": str(job_id),
                "render_time_ms": payload.render_time_ms,
                "output_size_bytes": payload.output_size_bytes,
                "output_duration_ms": payload.output_duration_ms,
            },
        )
    elif payload.status == "failed":
        logger.warning(
            "render_job_failed",
            extra={"job_id": str(job_id), "error": payload.error},
        )
    else:
        logger.info(
            "render_status_updated",
            extra={"job_id": str(job_id), "status": payload.status},
        )
    return {"ok": True, "job_id": str(job_id), "status": payload.status}


@router.get("/{video_id}/media-source", response_model=MediaSourceResponse)
async def get_media_source(
    video_id: str,
    x_heimdex_org_id: Annotated[str, Header(..., alias="X-Heimdex-Org-Id")],
    _token: Annotated[str, Depends(verify_internal_token)],
    drive_file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
):
    """Returns the media source info for the video.

    For gdrive videos (gd_ prefix): returns proxy S3 key from DriveFile.
    For other source types: returns 404 (extend as needed).
    """
    org_id = _parse_org_id(x_heimdex_org_id)

    if not video_id.startswith("gd_"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unsupported video source type for video_id: {video_id}",
        )

    drive_file = await drive_file_repo.get_by_video_id(org_id, video_id)
    if drive_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video not found: {video_id}",
        )

    return MediaSourceResponse(
        video_id=video_id,
        source_type="gdrive",
        proxy_s3_key=drive_file.proxy_s3_key,
        google_file_id=drive_file.google_file_id,
    )
