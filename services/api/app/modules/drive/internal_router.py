"""
Internal drive job management router for drive-workers.

Endpoints allow workers to claim pending jobs, update enrichment status,
and fetch file metadata — all over HTTP instead of direct DB access.

POST  /internal/drive/jobs/claim          — Atomic claim with SELECT FOR UPDATE SKIP LOCKED
PATCH /internal/drive/jobs/{file_id}/status — Update enrichment status + recompute enrichment_state
GET   /internal/drive/files/{file_id}      — Return minimal file metadata for processing

Auth: Pre-shared internal API key (Bearer token) via DRIVE_INTERNAL_API_KEY.
Feature-gated: only registered when DRIVE_CONNECTOR_ENABLED=true.

Lease tokens: Each claimed job receives a UUID lease_token with an expiry.
Status updates must present the matching lease_token; mismatches yield 409.
"""
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status as http_status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

import asyncio


from app.dependencies import get_db_session
from app.logging_config import get_logger
from app.modules.drive.internal_schemas import (
    ClaimedFileInfo,
    ClaimJobsRequest,
    ClaimJobsResponse,
    DriveFileMetadataResponse,
    UpdateJobStatusRequest,
    UpdateJobStatusResponse,
)
from app.modules.drive.models import DriveFile
from app.modules.drive.repository import _compute_enrichment_state

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/drive", tags=["internal-drive"])

# Lease duration: 10 minutes. Workers must complete within this window.
LEASE_DURATION_SECONDS = 600

# Terminal statuses that cannot transition back to running.
_TERMINAL_STATUSES = frozenset({"done", "failed"})


from app.dependencies import verify_internal_token as _verify_internal_token


def _mask_lease_token(token: str | None) -> str:
    """Return last 6 chars of lease_token for safe logging."""
    if not token:
        return "none"
    return f"...{token[-6:]}"


# ── Claim jobs ────────────────────────────────────────────────────────

_STATUS_COLUMN_MAP = {
    "caption": "caption_status",
    "stt": "stt_status",
    "ocr": "ocr_status",
    "face": "face_status",
}

_ERROR_COLUMN_MAP = {
    "caption": "caption_error",
    "stt": "enrichment_error",
    "ocr": "enrichment_error",
    "face": "face_error",
}

_PREREQUISITE_MAP = {
    "caption": lambda: DriveFile.keyframe_s3_prefix.isnot(None),
    "stt": lambda: DriveFile.audio_s3_key.isnot(None),
    "ocr": lambda: DriveFile.keyframe_s3_prefix.isnot(None),
    "face": lambda: DriveFile.keyframe_s3_prefix.isnot(None),
}


@router.post("/jobs/claim", response_model=ClaimJobsResponse)
async def claim_jobs(
    request: ClaimJobsRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Atomically claim pending enrichment jobs using SELECT FOR UPDATE SKIP LOCKED.

    Each claimed file receives a lease_token (UUID) and lease_expires_at.
    Only files that are pending AND (not leased OR lease expired) can be claimed.
    """
    t0 = time.monotonic()

    status_col = _STATUS_COLUMN_MAP.get(request.job_type)
    if status_col is None:
        # visual_embed has no DB status column — return empty claim
        return ClaimJobsResponse(files=[])

    prerequisite = _PREREQUISITE_MAP.get(request.job_type)
    now = datetime.now(timezone.utc)

    query = (
        select(DriveFile)
        .where(
            getattr(DriveFile, status_col) == "pending",
            DriveFile.is_deleted.is_(False),
            # Only claim files with no active lease
            or_(
                DriveFile.lease_token.is_(None),
                DriveFile.lease_expires_at < now,
            ),
        )
        .order_by(DriveFile.created_at.asc())
        .limit(request.limit)
        .with_for_update(skip_locked=True)
    )
    if prerequisite is not None:
        query = query.where(prerequisite())

    result = await db.execute(query)
    files = list(result.scalars().all())

    lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

    # Mark claimed files as "running" and assign lease tokens
    for f in files:
        setattr(f, status_col, "running")
        f.lease_token = str(_uuid.uuid4())
        f.lease_expires_at = lease_expires_at
    if files:
        await db.flush()

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_drive_jobs_claimed",
        job_type=request.job_type,
        claimed_count=len(files),
        latency_ms=latency_ms,
        file_ids=[str(f.id) for f in files],
    )

    return ClaimJobsResponse(
        files=[
            ClaimedFileInfo(
                id=f.id,
                org_id=f.org_id,
                video_id=f.video_id,
                keyframe_s3_prefix=f.keyframe_s3_prefix,
                audio_s3_key=f.audio_s3_key,
                lease_token=f.lease_token,
                lease_expires_at=f.lease_expires_at,
            )
            for f in files
        ]
    )


# ── Update job status ─────────────────────────────────────────────────

@router.patch("/jobs/{file_id}/status", response_model=UpdateJobStatusResponse)
async def update_job_status(
    file_id: UUID,
    request: UpdateJobStatusRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Update enrichment status for a specific job type and recompute enrichment_state.

    Lease enforcement:
    - If the file has a lease_token, request.lease_token must match.
    - If the lease has expired, returns 409.

    Idempotency:
    - Re-sending the same terminal status (done/failed) is safe → returns ok=True.
    - Attempting to set "running" on a terminal status → returns 409.
    """
    t0 = time.monotonic()

    status_col = _STATUS_COLUMN_MAP.get(request.job_type)
    if status_col is None:
        # visual_embed has no DB status column — accept the call as a no-op
        logger.info(
            "internal_drive_job_status_noop",
            file_id=str(file_id),
            job_type=request.job_type,
            status=request.status,
        )
        return UpdateJobStatusResponse(ok=True)

    error_col = _ERROR_COLUMN_MAP.get(request.job_type)
    result = await db.execute(
        select(DriveFile).where(DriveFile.id == file_id)
    )
    drive_file = result.scalar_one_or_none()
    if drive_file is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Drive file not found: {file_id}",
        )

    current_status = getattr(drive_file, status_col)

    # ── Idempotency: re-sending same terminal status is safe ──
    if current_status in _TERMINAL_STATUSES and request.status == current_status:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "internal_drive_job_status_idempotent",
            file_id=str(file_id),
            job_type=request.job_type,
            status=request.status,
            latency_ms=latency_ms,
            lease_token=_mask_lease_token(request.lease_token),
        )
        return UpdateJobStatusResponse(ok=True)

    # ── Lease enforcement ──
    if drive_file.lease_token is not None:
        if request.lease_token is None or request.lease_token != drive_file.lease_token:
            logger.warning(
                "internal_drive_lease_token_mismatch",
                file_id=str(file_id),
                job_type=request.job_type,
                expected=_mask_lease_token(drive_file.lease_token),
                received=_mask_lease_token(request.lease_token),
            )
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="lease_token_mismatch",
            )
        now = datetime.now(timezone.utc)
        if drive_file.lease_expires_at and drive_file.lease_expires_at < now:
            logger.warning(
                "internal_drive_lease_expired",
                file_id=str(file_id),
                job_type=request.job_type,
                lease_token=_mask_lease_token(drive_file.lease_token),
                expired_at=drive_file.lease_expires_at.isoformat(),
            )
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="lease_expired",
            )

    # Build the four status values for enrichment_state computation.
    # The current request overrides the stored value for its job_type.
    stt = request.status if request.job_type == "stt" else drive_file.stt_status
    ocr = request.status if request.job_type == "ocr" else drive_file.ocr_status
    caption = request.status if request.job_type == "caption" else drive_file.caption_status
    face = request.status if request.job_type == "face" else getattr(drive_file, "face_status", None)

    new_state = _compute_enrichment_state(stt, ocr, caption, face)
    values: dict[str, object] = {
        status_col: request.status,
        "enrichment_state": new_state,
        "enrichment_updated_at": func.now(),
        # Clear lease on terminal status
        "lease_token": None,
        "lease_expires_at": None,
    }
    if request.error is not None and error_col is not None:
        values[error_col] = request.error
    await db.execute(
        update(DriveFile).where(DriveFile.id == file_id).values(**values)
    )
    await db.flush()

    # Deferred caption: when STT completes on legacy/GPU-transcode pipeline,
    # publish caption jobs that were deferred at "indexed" time.
    # Transcript data is now in OpenSearch — fetch it so the caption worker
    # can build VLM prompts with transcript context.
    if (
        request.job_type == "stt"
        and request.status == "done"
        and drive_file.scene_count
        and drive_file.scene_count > 0
        and drive_file.keyframe_s3_prefix
    ):
        _vid = drive_file.video_id
        _kf_prefix = drive_file.keyframe_s3_prefix
        _sc = drive_file.scene_count
        _org_id = drive_file.org_id

        # Fetch transcripts from OpenSearch (STT enrichment already completed)
        from app.modules.search.scene_client import SceneSearchClient
        scene_client = SceneSearchClient()
        try:
            scene_transcripts = await scene_client.get_scene_transcripts(
                _org_id, _vid, _sc
            )
        except Exception:
            logger.warning(
                "deferred_caption_transcript_fetch_failed",
                file_id=str(file_id),
                video_id=_vid,
            )
            scene_transcripts = {}
        finally:
            await scene_client.close()

        scenes_for_caption = [
            {
                "scene_id": f"{_vid}_scene_{i:03d}",
                "scene_index": i,
                "keyframe_s3_key": f"{_kf_prefix}{_vid}_scene_{i:03d}.jpg",
                "transcript_raw": scene_transcripts.get(
                    f"{_vid}_scene_{i:03d}", ""
                ),
            }
            for i in range(_sc)
        ]
        from app.sqs_producer import publish_scene_enrichment_jobs
        asyncio.create_task(
            asyncio.get_running_loop().run_in_executor(
                None,
                lambda: publish_scene_enrichment_jobs(
                    file_id=file_id,
                    org_id=_org_id,
                    video_id=_vid,
                    scenes=scenes_for_caption,
                    job_types=("caption",),
                ),
            )
        )
        logger.info(
            "deferred_caption_jobs_published",
            file_id=str(file_id),
            video_id=_vid,
            scene_count=_sc,
            scenes_with_transcript=len(scene_transcripts),
        )

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_drive_job_status_updated",
        file_id=str(file_id),
        job_type=request.job_type,
        status=request.status,
        enrichment_state=new_state,
        latency_ms=latency_ms,
        lease_token=_mask_lease_token(request.lease_token),
    )
    return UpdateJobStatusResponse(ok=True)


# ── Get file metadata ─────────────────────────────────────────────────

@router.get("/files/{file_id}", response_model=DriveFileMetadataResponse)
async def get_file_metadata(
    file_id: UUID,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Return minimal file metadata needed by workers for processing."""
    t0 = time.monotonic()

    result = await db.execute(
        select(DriveFile).where(DriveFile.id == file_id)
    )
    drive_file = result.scalar_one_or_none()
    if drive_file is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Drive file not found: {file_id}",
        )

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_drive_file_metadata_fetched",
        file_id=str(file_id),
        latency_ms=latency_ms,
    )

    return DriveFileMetadataResponse(
        id=drive_file.id,
        org_id=drive_file.org_id,
        video_id=drive_file.video_id,
        keyframe_s3_prefix=drive_file.keyframe_s3_prefix,
        audio_s3_key=drive_file.audio_s3_key,
        caption_status=drive_file.caption_status,
        stt_status=drive_file.stt_status,
        ocr_status=drive_file.ocr_status,
        face_status=drive_file.face_status,
        enrichment_state=drive_file.enrichment_state,
    )
