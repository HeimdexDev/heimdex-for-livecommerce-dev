from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.dependencies import get_drive_file_repository, verify_internal_token
from app.logging_config import get_logger
from app.modules.drive.repository import DriveFileRepository
from app.modules.shorts_render import post_render_hook
from app.modules.shorts_render.repository import ShortsRenderJobRepository
from app.modules.shorts_render.schemas import RenderStatusUpdate

# Use structlog so structured fields (job_id, render_time_ms, etc.)
# reach the JSON formatter — same fix as in the rest of shorts_render.
logger = get_logger(__name__)

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
    """Called by render worker to report job completion/failure.

    For ``status='completed'``: uses ``repo.complete_idempotent`` so
    a double-delivered worker callback (SQS redelivery, network
    retry) flips the row exactly once. The post-render Whisper
    refinement hook only fires when this call was the one that did
    the flip — preventing duplicate refinement renders.

    Other statuses (``rendering``, ``failed``) still use
    ``update_status`` since they have no idempotency-sensitive side
    effects.
    """
    repo = ShortsRenderJobRepository(db)

    if payload.status == "completed":
        # Existence check first — distinguishes 404 (no row) from
        # 200-no-op (row already completed). complete_idempotent
        # alone returns False for both cases.
        existing = await repo._get_by_id_internal(job_id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        did_flip = await repo.complete_idempotent(
            job_id,
            output_s3_key=payload.output_s3_key,
            output_duration_ms=payload.output_duration_ms,
            output_size_bytes=payload.output_size_bytes,
            render_time_ms=payload.render_time_ms,
        )
        # Commit explicitly so the post-render hook reads
        # post-commit state (without this, the runner could open a
        # new session before the request session's auto-commit and
        # see the row in pre-completed state).
        await db.commit()

        if did_flip:
            logger.info(
                "render_job_completed",
                **{
                    "job_id": str(job_id),
                    "render_time_ms": payload.render_time_ms,
                    "output_size_bytes": payload.output_size_bytes,
                    "output_duration_ms": payload.output_duration_ms,
                },
            )
            # Fire-and-forget. Hook is defense-in-depth on its own
            # exception path; this try/except is belt-and-suspenders.
            try:
                post_render_hook.schedule_refinement_if_eligible(
                    parent_job_id=job_id,
                    org_id=existing.org_id,  # type: ignore[arg-type]
                )
            except Exception:
                logger.exception(
                    "post_render_hook_invocation_failed",
                    **{"job_id": str(job_id)},
                )
        else:
            logger.info(
                "render_job_completed_idempotent_noop",
                **{"job_id": str(job_id)},
            )
        return {"ok": True, "job_id": str(job_id), "status": payload.status}

    # Non-completed: keep the original update_status path unchanged.
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

    if payload.status == "failed":
        logger.warning(
            "render_job_failed",
            **{"job_id": str(job_id), "error": payload.error},
        )
    else:
        logger.info(
            "render_status_updated",
            **{"job_id": str(job_id), "status": payload.status},
        )
    return {"ok": True, "job_id": str(job_id), "status": payload.status}


@router.get("/{video_id}/media-source", response_model=MediaSourceResponse)
async def get_media_source(
    video_id: str,
    _token: Annotated[str, Depends(verify_internal_token)],
    drive_file_repo: Annotated[DriveFileRepository, Depends(get_drive_file_repository)],
    x_heimdex_org_id: Annotated[str | None, Header(alias="X-Heimdex-Org-Id")] = None,
):
    """Returns the media source info for the video.

    For gdrive videos (gd_ prefix): returns proxy S3 key from DriveFile.
    For other source types: returns 404 (extend as needed).

    Auth (Pattern B, post-2026-05-01): bearer authenticates the call;
    the resource's ``org_id`` is the canonical tenant context.
    ``X-Heimdex-Org-Id`` is OPTIONAL and treated as a cross-validation
    only — see ``app/lib/internal_auth.py``.
    """
    from app.lib.internal_auth import resolve_resource_with_org

    if not video_id.startswith("gd_"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unsupported video source type for video_id: {video_id}",
        )

    drive_file, _org_id = await resolve_resource_with_org(
        resource_id=video_id,
        x_heimdex_org_id=x_heimdex_org_id,
        lookup_fn=drive_file_repo.get_by_video_id_resource_scoped,
        not_found_detail=f"Video not found: {video_id}",
    )

    return MediaSourceResponse(
        video_id=video_id,
        source_type="gdrive",
        proxy_s3_key=drive_file.proxy_s3_key,
        google_file_id=drive_file.google_file_id,
    )
