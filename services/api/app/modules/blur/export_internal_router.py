"""Internal callbacks for drive-blur-worker's layer export task.

Mirrors :mod:`app.modules.blur.internal_router` but scoped to
:class:`BlurExport`. Two endpoints only:

* ``POST /internal/blur/exports/{export_id}/claim`` — atomic
  ``queued → running`` with a fresh lease token. The response includes
  the parent ``blur_jobs`` row's ``source_s3_key`` + the category
  subset of ``mask_s3_keys``, so the worker can do everything in one
  round-trip.
* ``POST /internal/blur/exports/{export_id}/complete`` — terminal
  state update carrying the uploaded ``.mov`` key.

No heartbeat endpoint — layer export is CPU-bound and bounded by
source video length; if it blows the lease the watchdog can reap the
row and the customer re-clicks Export.
"""

from __future__ import annotations

import logging
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.dependencies import verify_internal_token
from app.modules.blur.export_repository import BlurExportRepository
from app.modules.blur.models import (
    BLUR_STATUS_CANCELLED,
    BLUR_STATUS_QUEUED,
    BLUR_STATUS_RUNNING,
    BlurExport,
)
from app.modules.blur.repository import BlurJobRepository
from app.modules.blur.schemas import (
    BlurExportClaim,
    BlurExportCompletePayload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/blur/exports", tags=["internal-blur"])


@router.post("/{export_id}/claim", response_model=BlurExportClaim)
async def claim_blur_export(
    export_id: UUID,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> BlurExportClaim:
    """Atomic ``queued → running`` for a layer export + payload bundle.

    The worker receives the original proxy key AND the exact subset of
    per-category masks it needs to composite. We resolve both from the
    parent :class:`BlurJob` row (the export row only holds the category
    list, not the keys) so a single query returns the full plan.
    """
    settings = get_settings()
    export_repo = BlurExportRepository(db)
    job_repo = BlurJobRepository(db)

    existing = await export_repo.get_by_id_internal(export_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blur export not found",
        )
    if existing.status == BLUR_STATUS_CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Blur export was cancelled",
        )
    if existing.status != BLUR_STATUS_QUEUED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Blur export is in status={existing.status!r}, expected queued",
        )

    # Resolve parent job to pull source key + category masks. We do this
    # BEFORE the atomic claim so a missing / half-deleted parent yields
    # a clean 409 without leaving the export stuck in running.
    parent = await job_repo.get_by_id_internal(existing.blur_job_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parent blur job is missing",
        )
    if not parent.mask_s3_keys:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parent blur job has no mask layers — cannot compose export",
        )

    requested_categories = tuple(existing.categories or [])
    # Filter the parent's mask keys to just what this export asked for.
    selected_masks: dict[str, str] = {}
    missing: list[str] = []
    for category in requested_categories:
        key = parent.mask_s3_keys.get(category)
        if key is None:
            missing.append(category)
        else:
            selected_masks[category] = key
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Parent job is missing mask layers for categories "
                f"{sorted(missing)} — cannot compose export"
            ),
        )

    claimed = await export_repo.claim(
        export_id=export_id,
        lease_seconds=settings.blur_lease_seconds,
    )
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Blur export was claimed by another worker",
        )
    row, lease_token = claimed
    assert row.lease_expires_at is not None
    logger.info(
        "blur_export_claimed",
        export_id=str(export_id), lease_token=str(lease_token),
    )
    return BlurExportClaim(
        id=cast(UUID, row.id),
        org_id=row.org_id,
        file_id=row.file_id,
        video_id=row.video_id,
        blur_job_id=row.blur_job_id,
        source_s3_key=parent.source_s3_key,
        mask_s3_keys=cast(dict, selected_masks),  # type: ignore[type-arg]
        categories=requested_categories,  # type: ignore[arg-type]
        format=row.format,  # type: ignore[arg-type]
        lease_token=lease_token,
        lease_expires_at=row.lease_expires_at,
    )


@router.post("/{export_id}/complete")
async def complete_blur_export(
    export_id: UUID,
    payload: BlurExportCompletePayload,
    _token: Annotated[str, Depends(verify_internal_token)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    """Terminal transition from the export worker.

    Matches the blur-job complete endpoint's lease-token + state guards.
    """
    export_repo = BlurExportRepository(db)

    existing = await export_repo.get_by_id_internal(export_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Blur export not found",
        )
    if existing.status == BLUR_STATUS_CANCELLED:
        logger.info("blur_export_complete_after_cancel", export_id=str(export_id))
        return {
            "ok": False,
            "export_id": str(export_id),
            "reason": "cancelled",
            "cleanup_required": True,
        }
    if existing.status != BLUR_STATUS_RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Blur export is in status={existing.status!r}, expected running",
        )

    refreshed = await export_repo.complete(
        export_id=export_id,
        lease_token=payload.lease_token,
        status=payload.status,
        layer_s3_key=payload.layer_s3_key,
        error=payload.error,
    )
    if refreshed is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lease token mismatch or export no longer running",
        )
    logger.info(
        "blur_export_completed",
        export_id=str(export_id),
        status=payload.status,
    )
    return {"ok": True, "export_id": str(export_id), "status": payload.status}
