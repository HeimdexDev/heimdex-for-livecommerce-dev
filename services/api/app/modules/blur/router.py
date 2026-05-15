"""Public blur job routes.

All routes require authentication and org context. Rate-limited per
``(org, user)``. Scoped by ``file_id`` in the path so the caller's
authority to operate on the underlying video is enforced at the
drive-file repository layer (same pattern as shorts-render).
"""

from __future__ import annotations

import logging
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.responses import RedirectResponse

from app.db.base import get_db_session
from app.dependencies import get_blur_export_service, get_blur_service
from app.modules.auth.service import get_current_user
from app.modules.blur.export_service import BlurExportService
from app.modules.blur.rate_limit import require_blur_rate_limit
from app.modules.blur.schemas import (
    BlurExportResponse,
    BlurJobListResponse,
    BlurJobResponse,
    CreateBlurExportRequest,
    CreateBlurJobRequest,
)
from app.modules.blur.service import BlurService
from app.modules.drive.models import DriveFile
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/blur", tags=["blur"])


async def _resolve_file_id(
    file_id_or_video_id: str,
    org_id: UUID,
    db: AsyncSession,
) -> UUID:
    """Accept either a UUID file_id or a video_id string (e.g. gd_...)."""
    try:
        return UUID(file_id_or_video_id)
    except ValueError:
        pass
    row = await db.execute(
        select(DriveFile.id).where(
            DriveFile.org_id == org_id,
            DriveFile.video_id == file_id_or_video_id,
        ).limit(1)
    )
    result = row.scalar_one_or_none()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No drive file found for video_id={file_id_or_video_id}",
        )
    return result


@router.post(
    "/videos/{file_id}",
    response_model=BlurJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_blur_job(
    file_id: str,
    body: CreateBlurJobRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BlurService, Depends(get_blur_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _rate_limit: Annotated[None, Depends(require_blur_rate_limit)] = None,
) -> BlurJobResponse:
    """Enqueue a user-triggered blur run for the given video file."""
    resolved = await _resolve_file_id(file_id, org_ctx.org_id, db)
    return await service.create_blur_job(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        file_id=resolved,
        payload=body,
    )


@router.get(
    "/videos/{file_id}",
    response_model=BlurJobListResponse,
)
async def list_blur_jobs_for_video(
    file_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BlurService, Depends(get_blur_service)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> BlurJobListResponse:
    resolved = await _resolve_file_id(file_id, org_ctx.org_id, db)
    return await service.list_blur_jobs_for_file(
        org_id=org_ctx.org_id,
        file_id=resolved,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=BlurJobResponse,
)
async def get_blur_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BlurService, Depends(get_blur_service)],
) -> BlurJobResponse:
    return await service.get_blur_job(org_id=org_ctx.org_id, job_id=job_id)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=BlurJobResponse,
)
async def cancel_blur_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BlurService, Depends(get_blur_service)],
) -> BlurJobResponse:
    """Cancel a queued job. Returns 409 if the job is already running/done/failed/cancelled."""
    return await service.cancel_blur_job(org_id=org_ctx.org_id, job_id=job_id)


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_blur_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BlurService, Depends(get_blur_service)],
) -> Response:
    await service.delete_blur_job(org_id=org_ctx.org_id, job_id=job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- layer export (ProRes 4444 + alpha) ----------


@router.post(
    "/jobs/{job_id}/export",
    response_model=BlurExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_blur_export(
    job_id: UUID,
    body: CreateBlurExportRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    export_service: Annotated[BlurExportService, Depends(get_blur_export_service)],
    _rate_limit: Annotated[None, Depends(require_blur_rate_limit)] = None,
) -> BlurExportResponse:
    """Enqueue a layer export for a done blur job.

    Customer picks a category subset (must be a subset of the parent's
    ``mask_s3_keys``) and a format (``prores_4444`` for v1). Returns
    202 with the new export row. Rate-limited by the same bucket as
    blur job creation.
    """
    return await export_service.create_export(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        blur_job_id=job_id,
        payload=body,
    )


@router.get(
    "/exports/{export_id}",
    response_model=BlurExportResponse,
)
async def get_blur_export(
    export_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    export_service: Annotated[BlurExportService, Depends(get_blur_export_service)],
) -> BlurExportResponse:
    return await export_service.get_export(
        org_id=org_ctx.org_id, export_id=export_id,
    )


@router.get(
    "/exports/{export_id}/download",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
async def download_blur_export(
    export_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    export_service: Annotated[BlurExportService, Depends(get_blur_export_service)],
) -> RedirectResponse:
    """Redirect to a fresh presigned URL for the exported ``.mov``.

    ``307 Temporary Redirect`` keeps the method semantics (GET stays
    GET) and makes ``<a href="...">`` downloads work without JS.
    """
    url = await export_service.generate_download_url(
        org_id=org_ctx.org_id, export_id=export_id,
    )
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
