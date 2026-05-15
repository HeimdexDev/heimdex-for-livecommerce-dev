"""Public routes for shorts-auto product mode v2.

Mounted under ``/api/shorts/auto/products`` (catalog + scan + clip)
and ``/api/shorts/auto/jobs`` (job lifecycle). All routes require an
authenticated user and a resolved org context.

Tenant isolation: every public method on
:class:`ProductScanService` already filters on ``org_id`` from the
:class:`OrgContext` dependency; this router only forwards the
context, never trusting path-supplied org / user ids.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.base import get_db_session
from app.modules.auth.service import get_current_user
from app.modules.shorts_auto_product.schemas import (
    ClipRequest,
    ClipResponse,
    JobStatusResponse,
    ProductCatalogResponse,
    ProductV2AvailabilityFragment,
    RescanResponse,
    ScanOrderCommitRequest,
    ScanOrderCreateRequest,
    ScanOrderResponse,
    ScanOrderStatusResponse,
    ScanRequest,
    ScanResponse,
)
from app.modules.shorts_auto_product.service import ProductScanService
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

logger = logging.getLogger(__name__)

# Mount under /api/shorts/auto so the existing v1 endpoints
# (/api/shorts/auto-select, /auto-render, /auto-availability) keep
# working unchanged. The /products/* and /jobs/* sub-trees are
# v2-only.
#
# main.py adds the ``/api`` prefix on include_router; this router
# only carries the in-module prefix, mirroring shorts_auto/router.py.
router = APIRouter(prefix="/shorts/auto", tags=["shorts-auto-product-v2"])


def _build_service(
    db: AsyncSession,
    settings: Settings,
) -> ProductScanService:
    return ProductScanService(session=db, settings=settings)


# MX-6 dev-only: 정적 시드된 wizard parent/children의 progress_pct를
# started_at 기준 elapsed 에 비례해서 응답 시점에 덮어쓴다. 워커가
# 없어도 진행률 바가 자연스럽게 움직이는 mock UX 제공. config 의
# ``mock_wizard_auto_progress`` 가 True 일 때만 동작.
_ACTIVE_PROGRESS_STAGES: frozenset[str] = frozenset(
    {"enumerating", "tracking", "assembling", "rendering"}
)


def _apply_mock_auto_progress(response: ScanOrderStatusResponse) -> None:
    now = datetime.now(timezone.utc)
    for job in (response.parent, *response.children):
        if job.stage not in _ACTIVE_PROGRESS_STAGES:
            continue
        if job.started_at is None:
            continue
        elapsed_s = max(0.0, (now - job.started_at).total_seconds())
        # 20초마다 100% 도달 — dev 시각 검증에 충분한 속도.
        job.progress_pct = min(100, int(elapsed_s * 5))


async def _resolve_video_uuid(
    *, db: AsyncSession, org_id: UUID, video_id: str,
) -> UUID:
    """Resolve the OS-style ``video_id`` (``gd_xxx``) to its DriveFile UUID.

    Every wizard / product-v2 router endpoint takes ``video_id`` from
    the path as a STRING (matching the frontend's ``/videos/{videoId}``
    URL convention), but the service layer + DB columns are typed
    ``UUID`` because that's the DriveFile primary key. This helper
    bridges the two by querying ``DriveFileRepository.get_by_video_id``
    (which already filters soft-deleted rows).

    Returns:
        The resolved ``DriveFile.id`` UUID.

    Raises:
        HTTPException 404: ``video_id`` does not resolve to an active
            DriveFile in this org. Same shape as the stale-video guard
            in ``internal_router.complete``.

    Loose-coupling note (plan §15): drive-repo lookup is lazy-imported
    here, mirroring the carve-out in ``internal_router.complete``. The
    router stays free of module-level ``app.modules.drive`` coupling.
    """
    from app.modules.drive.repository import DriveFileRepository

    drive_file = await DriveFileRepository(db).get_by_video_id(
        org_id=org_id, video_id=video_id,
    )
    if drive_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"video_id {video_id!r} not found",
        )
    return drive_file.id


# ----------------------------------------------------------------------
# GET /api/shorts/auto/products/{video_id}
# ----------------------------------------------------------------------

@router.get(
    "/products/{video_id}",
    response_model=ProductCatalogResponse,
)
async def get_product_catalog(
    video_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductCatalogResponse:
    """List enumerated products for a video.

    Path param accepts the OS-style ``video_id`` string (``gd_xxx``);
    the handler resolves it to the DriveFile UUID before passing to the
    service layer. See :func:`_resolve_video_uuid` for the rationale.

    Empty ``products`` array + ``scan_status="never"`` means the user
    should see the "Scan for products" CTA. ``scan_status="in_progress"``
    means the toast subscription should be reattached to ``scan_job_id``.
    """
    video_uuid = await _resolve_video_uuid(
        db=db, org_id=org_ctx.org_id, video_id=video_id,
    )
    service = _build_service(db, settings)
    return await service.list_products(
        org_id=org_ctx.org_id, video_id=video_uuid,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/products/{video_id}/scan
# ----------------------------------------------------------------------

@router.post(
    "/products/{video_id}/scan",
    response_model=ScanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_scan(
    video_id: str,
    body: ScanRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScanResponse:
    """Enqueue an enumeration scan.

    Path accepts the OS-style ``video_id`` (``gd_xxx``); see
    :func:`_resolve_video_uuid`.

    Idempotent within ``auto_shorts_product_v2_scan_idempotency_seconds``
    (default 60s) per ``(video_id, user_id)``: re-clicking returns the
    existing job. 402 on cost cap. 429 on per-org concurrency cap.
    """
    video_uuid = await _resolve_video_uuid(
        db=db, org_id=org_ctx.org_id, video_id=video_id,
    )
    service = _build_service(db, settings)
    return await service.enqueue_scan(
        org_id=org_ctx.org_id,
        video_id=video_uuid,
        user_id=user.id,
        duration_preset_sec=body.duration_preset_sec,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/products/{video_id}/{catalog_entry_id}/clip
# ----------------------------------------------------------------------

@router.post(
    "/products/{video_id}/{catalog_entry_id}/clip",
    response_model=ClipResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_clip(
    video_id: str,
    catalog_entry_id: UUID,
    body: ClipRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ClipResponse:
    """Enqueue tracking + assembly + render for a chosen catalog entry.

    Path's ``video_id`` is the OS-style string (``gd_xxx``); see
    :func:`_resolve_video_uuid`. ``catalog_entry_id`` is a UUID
    (it IS the catalog row's primary key, so no resolution needed).

    Same idempotency / cap semantics as ``/scan`` but keyed on
    ``(video_id, user_id, catalog_entry_id)``.

    NOTE: Plan §4.2 marks this endpoint for deprecation (will return
    410 Gone after Phase 4 fully ships). The type fix here is a
    forward-compat hedge — keeps the endpoint working consistently
    until the 410 conversion lands.
    """
    video_uuid = await _resolve_video_uuid(
        db=db, org_id=org_ctx.org_id, video_id=video_id,
    )
    service = _build_service(db, settings)
    return await service.enqueue_clip(
        org_id=org_ctx.org_id,
        video_id=video_uuid,
        catalog_entry_id=catalog_entry_id,
        user_id=user.id,
        duration_preset_sec=body.duration_preset_sec,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/products/{video_id}/rescan
# ----------------------------------------------------------------------

@router.post(
    "/products/{video_id}/rescan",
    response_model=RescanResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def force_rescan(
    video_id: str,
    body: ScanRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RescanResponse:
    """Soft-reject the existing catalog and enqueue a fresh enumeration.

    Path accepts the OS-style ``video_id`` (``gd_xxx``); see
    :func:`_resolve_video_uuid`.

    Bypasses the 60s idempotency window — rescan is always intentional.
    Existing appearances cascade naturally (rejected catalog rows hide
    from the gallery; their appearances stay readable for forensics).
    """
    video_uuid = await _resolve_video_uuid(
        db=db, org_id=org_ctx.org_id, video_id=video_id,
    )
    service = _build_service(db, settings)
    return await service.rescan(
        org_id=org_ctx.org_id,
        video_id=video_uuid,
        user_id=user.id,
        duration_preset_sec=body.duration_preset_sec,
    )


# ----------------------------------------------------------------------
# DELETE /api/shorts/auto/products/{video_id}/{catalog_entry_id}
# ----------------------------------------------------------------------

@router.delete(
    "/products/{video_id}/{catalog_entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reject_catalog_entry(
    video_id: str,
    catalog_entry_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Soft-reject a catalog entry ("this isn't a product").

    Path's ``video_id`` is the OS-style string (``gd_xxx``); see
    :func:`_resolve_video_uuid`. ``catalog_entry_id`` is a UUID.

    v1: internal admin use. v2 will surface this in the picker UI for
    user-driven curation. Idempotent — already-rejected entries return
    204 silently.
    """
    video_uuid = await _resolve_video_uuid(
        db=db, org_id=org_ctx.org_id, video_id=video_id,
    )
    service = _build_service(db, settings)
    await service.reject_catalog_entry(
        org_id=org_ctx.org_id,
        video_id=video_uuid,
        catalog_entry_id=catalog_entry_id,
    )


# ----------------------------------------------------------------------
# GET /api/shorts/auto/jobs/{job_id}
# ----------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobStatusResponse:
    """Poll job status. Drives the in-app toast subscription."""
    service = _build_service(db, settings)
    return await service.get_job_status(
        org_id=org_ctx.org_id, job_id=job_id,
    )


# ----------------------------------------------------------------------
# POST /api/shorts/auto/jobs/{job_id}/cancel
# ----------------------------------------------------------------------

@router.post(
    "/jobs/{job_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Cancel an in-flight scan or clip job.

    Best-effort: marks the job ``cancelled``. The worker bails out at
    its next heartbeat. Already-terminal jobs return 404 (no info leak
    between not-found and already-done).
    """
    service = _build_service(db, settings)
    await service.cancel_job(org_id=org_ctx.org_id, job_id=job_id)


# ----------------------------------------------------------------------
# GET /api/shorts/auto/products-v2-availability
# ----------------------------------------------------------------------

@router.get(
    "/products-v2-availability",
    response_model=ProductV2AvailabilityFragment,
)
async def get_product_v2_availability(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ProductV2AvailabilityFragment:
    """Frontend reads this to decide whether to render the v2 UI.

    Plan §5 originally proposed merging this fragment into the
    existing ``/auto-availability`` payload. Phase 1 keeps it as a
    separate endpoint to avoid touching the v1 shorts-auto module —
    we can fold them together in a later phase if desired.
    """
    service = _build_service(db, settings)
    return await service.availability_fragment(org_id=org_ctx.org_id)


# ----------------------------------------------------------------------
# Phase 4 wizard — scan-order endpoints
# ----------------------------------------------------------------------


@router.post(
    "/scan-orders/videos/{video_id}",
    response_model=ScanOrderResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_scan_order(
    video_id: str,
    body: ScanOrderCreateRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScanOrderResponse:
    """Submit the 4-step wizard.

    Path param accepts the OpenSearch-style ``video_id`` string
    (``gd_{sha256(org_id:google_file_id)[:16]}`` per
    ``DriveFile.video_id``). The frontend's ``/videos/{videoId}``
    URL pattern uses this shape, and the wizard CTA threads it
    through unchanged. The handler resolves the DriveFile to its
    UUID before passing to the service layer (which persists
    ``ProductScanJob.video_id`` as a UUID FK).

    Body captures every wizard input. Idempotent within
    ``auto_shorts_product_v2_scan_order_idempotency_seconds``
    (default 60s) keyed on canonical-JSON ``settings_hash``.

    Validation chain (422 with descriptive messages):
    * ``length_seconds``: 10..120 (Pydantic Field bounds)
    * ``requested_count``: 1..50
    * ``requested_count * length_seconds <= 1800`` (aggregate cap)
    * If time-range provided: end > start AND
      ``(end - start) / count >= length_seconds * 1000``

    Returns 404 when the video_id doesn't resolve to an active
    DriveFile (missing or soft-deleted) — same shape as the
    stale-video guard in ``internal_router.complete``.
    """
    video_uuid = await _resolve_video_uuid(
        db=db, org_id=org_ctx.org_id, video_id=video_id,
    )
    service = _build_service(db, settings)
    return await service.enqueue_scan_order(
        org_id=org_ctx.org_id,
        video_id=video_uuid,
        user_id=user.id,
        body=body,
    )


@router.get(
    "/scan-orders/{parent_job_id}",
    response_model=ScanOrderStatusResponse,
)
async def get_scan_order_status(
    parent_job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ScanOrderStatusResponse:
    """Aggregate status for a wizard order — parent + all children +
    rollup counts. The wizard polls THIS endpoint, not the legacy
    ``/jobs/{job_id}`` flat shape.
    """
    service = _build_service(db, settings)
    response = await service.get_scan_order_status(
        org_id=org_ctx.org_id, parent_job_id=parent_job_id,
    )
    if settings.mock_wizard_auto_progress:
        _apply_mock_auto_progress(response)
    return response


@router.post(
    "/scan-orders/{parent_job_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_scan_order(
    parent_job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Cascade-cancel a scan order: parent + non-terminal children.

    Best-effort for in-flight children — the lease + claimed_by
    discipline means a running render won't be ripped out from
    under itself; the next heartbeat sees ``stage=cancelled`` and
    exits cleanly.
    """
    service = _build_service(db, settings)
    await service.cancel_scan_order(
        org_id=org_ctx.org_id, parent_job_id=parent_job_id,
    )


@router.post(
    "/scan-orders/{parent_job_id}/commit",
    status_code=status.HTTP_202_ACCEPTED,
)
async def commit_scan_order(
    parent_job_id: UUID,
    body: ScanOrderCommitRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Phase 6 endpoint — preview → commit transition.

    Currently returns 501. The body shape is locked now so the
    frontend wizard can be built against a stable contract; Phase 6
    will wire the SAM2 + render-enqueue commit path.
    """
    service = _build_service(db, settings)
    await service.commit_scan_order(
        org_id=org_ctx.org_id,
        parent_job_id=parent_job_id,
        selected_window_ids=body.selected_window_ids,
    )
