"""Internal drive processing management router for drive-worker."""

import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.dependencies import get_db_session
from app.logging_config import get_logger
from app.modules.drive.internal_processing_schemas import (
    ClaimedProcessingFileInfo,
    ClaimProcessingRequest,
    ClaimProcessingResponse,
    UpdateProcessingStatusRequest,
    UpdateProcessingStatusResponse,
)
from app.modules.drive.internal_router import (
    LEASE_DURATION_SECONDS,
    _mask_lease_token,
    _verify_internal_token,
)
from app.modules.drive.models import DriveConnection, DriveFile
from app.config import get_settings
from app.sqs_producer import publish_enrichment_jobs, publish_transcode_job

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/drive/processing", tags=["internal-drive-processing"])

_TERMINAL_PROCESSING_STATUSES = frozenset({"indexed", "failed"})


def _build_drive_web_view_link(google_file_id: str) -> str:
    return f"https://drive.google.com/file/d/{google_file_id}/view"


@router.post("/claim", response_model=ClaimProcessingResponse)
async def claim_processing(
    request: ClaimProcessingRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Atomically claim pending files for processing using SKIP LOCKED."""
    t0 = time.monotonic()
    now = datetime.now(timezone.utc)

    query = (
        select(DriveFile, DriveConnection)
        .join(DriveConnection, DriveConnection.id == DriveFile.connection_id)
        .where(
            DriveFile.processing_status == "pending",
            DriveFile.is_deleted.is_(False),
            DriveFile.retry_count < DriveFile.max_retries,
            or_(
                DriveFile.lease_token.is_(None),
                DriveFile.lease_expires_at < now,
            ),
        )
        .order_by(DriveFile.created_at.asc())
        .limit(request.limit)
        .with_for_update(skip_locked=True)
    )

    result = await db.execute(query)
    rows = list(result.all())
    lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

    files: list[ClaimedProcessingFileInfo] = []
    for drive_file, connection in rows:
        token = str(_uuid.uuid4())
        drive_file.processing_status = "downloading"
        drive_file.lease_token = token
        drive_file.lease_expires_at = lease_expires_at
        files.append(
            ClaimedProcessingFileInfo(
                id=drive_file.id,
                org_id=drive_file.org_id,
                connection_id=drive_file.connection_id,
                google_file_id=drive_file.google_file_id,
                file_name=drive_file.file_name,
                video_id=drive_file.video_id,
                mime_type=drive_file.mime_type,
                md5_checksum=drive_file.md5_checksum,
                file_size_bytes=drive_file.file_size_bytes,
                drive_path=drive_file.drive_path,
                web_view_link=drive_file.web_view_link or _build_drive_web_view_link(drive_file.google_file_id),
                library_id=connection.library_id,
                scope_type=connection.scope_type,
                drive_id=connection.drive_id,
                google_created_time=drive_file.google_created_time,
                google_modified_time=drive_file.google_modified_time,
                lease_token=token,
                lease_expires_at=lease_expires_at,
            )
        )

    if rows:
        await db.flush()

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_processing_files_claimed",
        claimed_count=len(rows),
        latency_ms=latency_ms,
        file_ids=[str(drive_file.id) for drive_file, _ in rows],
    )
    return ClaimProcessingResponse(files=files)


@router.patch("/{file_id}/status", response_model=UpdateProcessingStatusResponse)
async def update_processing_status(
    file_id: UUID,
    request: UpdateProcessingStatusRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Update processing status and metadata for a claimed drive file."""
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

    if (
        drive_file.processing_status in _TERMINAL_PROCESSING_STATUSES
        and request.status == drive_file.processing_status
    ):
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "internal_processing_status_idempotent",
            file_id=str(file_id),
            status=request.status,
            latency_ms=latency_ms,
            lease_token=_mask_lease_token(request.lease_token),
        )
        return UpdateProcessingStatusResponse(ok=True)

    if drive_file.lease_token is not None:
        if request.lease_token is None or request.lease_token != drive_file.lease_token:
            logger.warning(
                "internal_processing_lease_token_mismatch",
                file_id=str(file_id),
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
                "internal_processing_lease_expired",
                file_id=str(file_id),
                lease_token=_mask_lease_token(drive_file.lease_token),
                expired_at=drive_file.lease_expires_at.isoformat(),
            )
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="lease_expired",
            )

    values: dict[str, object] = {}

    if request.status == "failed":
        next_retry_count = int(drive_file.retry_count) + 1
        should_retry = next_retry_count < int(drive_file.max_retries)
        values["retry_count"] = next_retry_count
        values["last_error"] = request.error
        values["last_attempt_at"] = func.now()
        values["processing_status"] = "pending" if should_retry else "failed"
        values["lease_token"] = None
        values["lease_expires_at"] = None
    elif request.status == "indexed":
        values["processing_status"] = "indexed"
        values["lease_token"] = None
        values["lease_expires_at"] = None
        if request.proxy_s3_key is not None:
            values["proxy_s3_key"] = request.proxy_s3_key
        if request.proxy_size_bytes is not None:
            values["proxy_size_bytes"] = request.proxy_size_bytes
        if request.proxy_duration_ms is not None:
            values["proxy_duration_ms"] = request.proxy_duration_ms
        if request.thumbnail_s3_prefix is not None:
            values["thumbnail_s3_prefix"] = request.thumbnail_s3_prefix
        if request.scene_count is not None:
            values["scene_count"] = request.scene_count
        if request.audio_s3_key is not None:
            values["audio_s3_key"] = request.audio_s3_key
        if request.keyframe_s3_prefix is not None:
            values["keyframe_s3_prefix"] = request.keyframe_s3_prefix
    elif request.status == "awaiting_transcode":
        values["processing_status"] = "awaiting_transcode"
        if request.original_s3_key is not None:
            values["original_s3_key"] = request.original_s3_key
        if request.original_size_bytes is not None:
            values["original_size_bytes"] = request.original_size_bytes
        # Release lease — drive-worker is done; transcode-worker uses SQS (no lease)
        values["lease_token"] = None
        values["lease_expires_at"] = None
    else:
        values["processing_status"] = request.status

    await db.execute(
        update(DriveFile).where(DriveFile.id == file_id).values(**values)
    )
    await db.flush()


    # SQS dual-write: publish enrichment jobs when processing completes.
    # Only fires when status transitions to 'indexed'; fire-and-forget.
    if values.get("processing_status") == "indexed":
        _eff_keyframe = (
            request.keyframe_s3_prefix
            if request.keyframe_s3_prefix is not None
            else drive_file.keyframe_s3_prefix
        )
        _eff_audio = (
            request.audio_s3_key
            if request.audio_s3_key is not None
            else drive_file.audio_s3_key
        )
        publish_enrichment_jobs(
            file_id=file_id,
            org_id=drive_file.org_id,
            video_id=drive_file.video_id,
            keyframe_s3_prefix=_eff_keyframe,
            audio_s3_key=_eff_audio,
        )

    # SQS: publish transcode job when drive-worker finishes original upload.
    # Only fires when drive_transcode_mode='gpu' and status is 'awaiting_transcode'.
    if values.get("processing_status") == "awaiting_transcode":
        settings = get_settings()
        if settings.drive_transcode_mode == "gpu":
            conn_result = await db.execute(
                select(DriveConnection).where(DriveConnection.id == drive_file.connection_id)
            )
            connection = conn_result.scalar_one_or_none()
            publish_transcode_job(
                file_id=file_id,
                org_id=drive_file.org_id,
                connection_id=drive_file.connection_id,
                video_id=drive_file.video_id,
                google_file_id=drive_file.google_file_id,
                file_name=drive_file.file_name,
                original_s3_key=request.original_s3_key or "",
                original_size_bytes=request.original_size_bytes or 0,
                library_id=connection.library_id if connection else drive_file.org_id,
                scope_type=connection.scope_type if connection else "full_drive",
                drive_id=connection.drive_id if connection else None,
            )

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_processing_status_updated",
        file_id=str(file_id),
        status=values.get("processing_status"),
        latency_ms=latency_ms,
        lease_token=_mask_lease_token(request.lease_token),
    )
    return UpdateProcessingStatusResponse(ok=True)
