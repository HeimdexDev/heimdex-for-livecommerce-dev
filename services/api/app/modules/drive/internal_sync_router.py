"""
Internal drive sync management router for drive-worker.

Endpoints allow the drive sync worker to claim connections, update sync cursors,
and upsert discovered files — all over HTTP instead of direct DB access.

POST  /internal/drive/sync/claim_connection                        — Atomic claim with SELECT FOR UPDATE SKIP LOCKED
PATCH /internal/drive/sync/connections/{connection_id}/checkpoint   — Update cursor fields + release lease
POST  /internal/drive/sync/connections/{connection_id}/upsert_files — Batch file upsert (idempotent)

Auth: Pre-shared internal API key (Bearer token) via DRIVE_INTERNAL_API_KEY.
Feature-gated: only registered when DRIVE_CONNECTOR_ENABLED=true.

Lease tokens: Each claimed connection receives a UUID lease_token with 10-min expiry.
Checkpoint/upsert must present the matching lease_token; mismatches yield 409.
"""
import hashlib
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.dependencies import get_db_session
from app.logging_config import get_logger
from app.modules.drive.internal_router import (
    LEASE_DURATION_SECONDS,
    _mask_lease_token,
    _verify_internal_token,
)
from app.modules.drive.internal_sync_schemas import (
    ClaimedConnectionInfo,
    ClaimSyncConnectionRequest,
    ClaimSyncConnectionResponse,
    SyncCheckpointRequest,
    SyncCheckpointResponse,
    UpsertFilesRequest,
    UpsertFilesResponse,
)
from app.modules.drive.models import DriveConnection, DriveFile

logger = get_logger(__name__)

router = APIRouter(prefix="/internal/drive/sync", tags=["internal-drive-sync"])

_MAX_UPSERT_ITEMS = 500


# ── Helpers ───────────────────────────────────────────────────────────

def _drive_video_id(org_id: str, google_file_id: str) -> str:
    """Deterministic video_id for Drive files.

    Canonical implementation: worker_sdk/drive_keys.py::drive_video_id
    Kept in sync — must produce identical output.
    """
    digest = hashlib.sha256(f"{org_id}:{google_file_id}".encode()).hexdigest()[:16]
    return f"gd_{digest}"


def _enforce_connection_lease(
    connection: DriveConnection,
    provided_token: str | None,
) -> None:
    """Validate lease_token on a connection. Raises 409 on mismatch/expiry."""
    if connection.lease_token is None:
        return  # No active lease — allow (backward compat during migration)

    if provided_token is None or provided_token != connection.lease_token:
        logger.warning(
            "internal_sync_lease_token_mismatch",
            connection_id=str(connection.id),
            expected=_mask_lease_token(connection.lease_token),
            received=_mask_lease_token(provided_token),
        )
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="lease_token_mismatch",
        )

    now = datetime.now(timezone.utc)
    if connection.lease_expires_at and connection.lease_expires_at < now:
        logger.warning(
            "internal_sync_lease_expired",
            connection_id=str(connection.id),
            lease_token=_mask_lease_token(connection.lease_token),
            expired_at=connection.lease_expires_at.isoformat(),
        )
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="lease_expired",
        )


# ── Claim connection ──────────────────────────────────────────────────

@router.post("/claim_connection", response_model=ClaimSyncConnectionResponse)
async def claim_sync_connection(
    request: ClaimSyncConnectionRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Atomically claim active connections for sync using SELECT FOR UPDATE SKIP LOCKED.

    Only connections that are active AND (not leased OR lease expired) can be claimed.
    Claimed connections receive a UUID lease_token with a 10-minute expiry.
    Order: least-recently-synced first (NULLs first for never-synced connections).
    """
    t0 = time.monotonic()
    now = datetime.now(timezone.utc)

    query = (
        select(DriveConnection)
        .where(
            DriveConnection.status == "active",
            or_(
                DriveConnection.lease_token.is_(None),
                DriveConnection.lease_expires_at < now,
            ),
        )
        .order_by(DriveConnection.last_sync_at.asc().nulls_first())
        .limit(request.limit)
        .with_for_update(skip_locked=True)
    )

    result = await db.execute(query)
    connections = list(result.scalars().all())

    lease_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

    claimed_infos: list[ClaimedConnectionInfo] = []
    for conn in connections:
        token = str(_uuid.uuid4())
        conn.lease_token = token
        conn.lease_expires_at = lease_expires_at
        claimed_infos.append(
            ClaimedConnectionInfo(
                connection_id=conn.id,
                org_id=conn.org_id,
                library_id=conn.library_id,
                scope_type=conn.scope_type,
                drive_id=conn.drive_id,
                folder_id=conn.folder_id,
                folder_name=conn.folder_name,
                folder_path=conn.folder_path,
                change_token=conn.change_token,
                last_sync_at=conn.last_sync_at,
                last_full_sync_at=conn.last_full_sync_at,
                lease_token=token,
                lease_expires_at=lease_expires_at,
            )
        )

    if connections:
        await db.flush()

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_sync_connections_claimed",
        claimed_count=len(connections),
        latency_ms=latency_ms,
        connection_ids=[str(c.id) for c in connections],
    )

    return ClaimSyncConnectionResponse(connections=claimed_infos)


# ── Checkpoint ────────────────────────────────────────────────────────

@router.patch(
    "/connections/{connection_id}/checkpoint",
    response_model=SyncCheckpointResponse,
)
async def checkpoint_connection(
    connection_id: UUID,
    request: SyncCheckpointRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Update sync cursor fields on a connection and optionally release the lease.

    Lease enforcement: lease_token must match the connection's active lease.
    If release=True (default), clears lease_token, lease_expires_at, and sync_requested_at,
    and sets last_sync_at to now() (unless an explicit value is provided).
    """
    t0 = time.monotonic()

    result = await db.execute(
        select(DriveConnection).where(DriveConnection.id == connection_id)
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )

    _enforce_connection_lease(connection, request.lease_token)

    values: dict[str, object] = {}
    if request.change_token is not None:
        values["change_token"] = request.change_token
    if request.last_sync_at is not None:
        values["last_sync_at"] = request.last_sync_at
    elif request.release:
        values["last_sync_at"] = func.now()
    if request.last_full_sync_at is not None:
        values["last_full_sync_at"] = request.last_full_sync_at
    if request.error_message is not None:
        values["error_message"] = request.error_message

    if request.release:
        values["lease_token"] = None
        values["lease_expires_at"] = None
        values["sync_requested_at"] = None

    if values:
        await db.execute(
            update(DriveConnection)
            .where(DriveConnection.id == connection_id)
            .values(**values)
        )
        await db.flush()

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_sync_checkpoint",
        connection_id=str(connection_id),
        release=request.release,
        fields_updated=list(values.keys()),
        latency_ms=latency_ms,
        lease_token=_mask_lease_token(request.lease_token),
    )

    return SyncCheckpointResponse(ok=True)


# ── Upsert files ──────────────────────────────────────────────────────

@router.post(
    "/connections/{connection_id}/upsert_files",
    response_model=UpsertFilesResponse,
)
async def upsert_files(
    connection_id: UUID,
    request: UpsertFilesRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Batch upsert discovered files for a connection.

    Idempotent: files that already exist (by org_id + google_file_id) are counted
    as unchanged and are NOT modified — matching the existing drive-worker discovery
    logic (discover.py: ``if existing: continue``).

    New files are created with processing_status="pending" and enrichment statuses
    set to "pending" (stt_status, ocr_status). caption_status is left NULL,
    matching the existing discovery logic in drive-worker.

    Duplicate provider_file_ids within a single batch are deduplicated.
    """
    t0 = time.monotonic()

    if len(request.items) > _MAX_UPSERT_ITEMS:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Too many items: {len(request.items)} (max {_MAX_UPSERT_ITEMS})",
        )

    conn_result = await db.execute(
        select(DriveConnection).where(DriveConnection.id == connection_id)
    )
    connection = conn_result.scalar_one_or_none()
    if connection is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Connection not found: {connection_id}",
        )

    _enforce_connection_lease(connection, request.lease_token)

    org_id = connection.org_id
    org_id_str = str(org_id)

    if not request.items:
        return UpsertFilesResponse(
            created_count=0, updated_count=0, unchanged_count=0, enqueued_jobs={},
        )

    provider_ids = [item.provider_file_id for item in request.items]
    existing_result = await db.execute(
        select(DriveFile.google_file_id).where(
            DriveFile.org_id == org_id,
            DriveFile.google_file_id.in_(provider_ids),
        )
    )
    existing_google_ids: set[str] = {row[0] for row in existing_result.all()}

    created_count = 0
    unchanged_count = 0
    seen_in_batch: set[str] = set()

    for item in request.items:
        if item.provider_file_id in existing_google_ids:
            unchanged_count += 1
            continue
        if item.provider_file_id in seen_in_batch:
            unchanged_count += 1
            continue
        seen_in_batch.add(item.provider_file_id)

        video_id = _drive_video_id(org_id_str, item.provider_file_id)
        drive_file = DriveFile(
            org_id=org_id,
            connection_id=connection_id,
            google_file_id=item.provider_file_id,
            file_name=item.name,
            mime_type=item.mime_type,
            file_size_bytes=item.size,
            md5_checksum=item.md5_checksum,
            google_modified_time=item.modified_time,
            drive_path=item.drive_path,
            video_id=video_id,
            processing_status="pending",
            enrichment_state="pending",
            stt_status="pending",
            ocr_status="pending",
        )
        db.add(drive_file)
        created_count += 1

    if created_count > 0:
        await db.flush()

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_sync_files_upserted",
        connection_id=str(connection_id),
        created_count=created_count,
        unchanged_count=unchanged_count,
        total_items=len(request.items),
        latency_ms=latency_ms,
        lease_token=_mask_lease_token(request.lease_token),
    )

    enqueued_jobs: dict[str, int] = {}
    if created_count > 0:
        enqueued_jobs = {"processing": created_count}

    return UpsertFilesResponse(
        created_count=created_count,
        updated_count=0,
        unchanged_count=unchanged_count,
        enqueued_jobs=enqueued_jobs,
    )
