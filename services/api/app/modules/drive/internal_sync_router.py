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
import json
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, status as http_status
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuthCredentials
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.config import get_settings
from app.dependencies import get_db_session, get_scene_opensearch_client
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
    ConnectionFileIdsResponse,
    DeleteFilesRequest,
    DeleteFilesResponse,
    SyncCheckpointRequest,
    SyncCheckpointResponse,
    TokenRequest,
    TokenResponse,
    UpdateMetadataRequest,
    UpdateMetadataResponse,
    UpsertFilesRequest,
    UpsertFilesResponse,
)
from app.modules.drive.models import DriveConnection, DriveFile, DriveSecret
from app.modules.search.scene_client import SceneSearchClient
from app.sqs_producer import publish_processing_job

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
    """Validate lease_token on a connection. Raises 409 on mismatch/expiry.

    When ``provided_token`` is None the check is skipped entirely.  This
    allows the processing path (which holds a *file* lease, not a connection
    lease) to obtain Google access tokens without conflicting with the
    discovery scheduler that periodically holds the connection lease.
    """
    if connection.lease_token is None:
        return  # No active lease — allow (backward compat during migration)
    if provided_token is None:
        return  # Caller has no connection lease — allow (processing path)

    if provided_token != connection.lease_token:
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


@router.post(
    "/connections/{connection_id}/token",
    response_model=TokenResponse,
)
async def get_connection_token(
    connection_id: UUID,
    request: TokenRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    """Return short-lived Google access token for claimed connection."""
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

    if connection.scope_type == "drive":
        secret_type = "service_account_key"
    elif connection.scope_type == "folder":
        secret_type = "oauth_token"
    else:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported scope_type: {connection.scope_type}",
        )

    secret_result = await db.execute(
        select(DriveSecret).where(
            DriveSecret.org_id == connection.org_id,
            DriveSecret.secret_type == secret_type,
        )
    )
    secret = secret_result.scalar_one_or_none()
    if secret is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Drive secret not found for org {connection.org_id}",
        )

    settings = get_settings()
    key = bytes.fromhex(settings.drive_sa_encryption_key)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(secret.nonce, secret.encrypted_value, None)
    secret_data = json.loads(plaintext.decode())

    if connection.scope_type == "drive":
        credentials = service_account.Credentials.from_service_account_info(
            secret_data,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
            subject=secret.impersonate_email,
        )
    else:
        credentials = OAuthCredentials(
            token=None,
            refresh_token=secret_data["refresh_token"],
            client_id=secret_data["client_id"],
            client_secret=secret_data["client_secret"],
            token_uri=secret_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        )

    credentials.refresh(GoogleAuthRequest())

    access_token = credentials.token
    expires_at = credentials.expiry
    if access_token is None or expires_at is None:
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail="failed_to_refresh_google_access_token",
        )

    return TokenResponse(
        access_token=access_token,
        token_type="Bearer",
        expires_at=expires_at,
        scope_type=connection.scope_type,
    )


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
        select(DriveFile).where(
            DriveFile.org_id == org_id,
            DriveFile.google_file_id.in_(provider_ids),
            DriveFile.is_deleted.is_(False),
        )
    )
    existing_files = existing_result.scalars().all()
    existing_files_map: dict[str, DriveFile] = {f.google_file_id: f for f in existing_files}
    existing_google_ids: set[str] = set(existing_files_map.keys())

    created_count = 0
    updated_count = 0
    new_files: list[DriveFile] = []
    modified_files: list[DriveFile] = []
    metadata_updates: list[dict[str, str]] = []
    unchanged_count = 0
    seen_in_batch: set[str] = set()

    for item in request.items:
        if item.provider_file_id in seen_in_batch:
            unchanged_count += 1
            continue
        seen_in_batch.add(item.provider_file_id)

        if item.provider_file_id in existing_google_ids:
            existing_file = existing_files_map[item.provider_file_id]

            changes_made = False

            if (
                item.md5_checksum
                and existing_file.md5_checksum
                and item.md5_checksum != existing_file.md5_checksum
            ):
                existing_file.md5_checksum = item.md5_checksum
                existing_file.file_size_bytes = item.size
                existing_file.google_modified_time = item.modified_time
                existing_file.processing_status = "pending"
                existing_file.enrichment_state = "pending"
                existing_file.stt_status = "pending"
                existing_file.ocr_status = "pending"
                existing_file.caption_status = "pending"
                existing_file.face_status = "pending"
                existing_file.proxy_s3_key = None
                existing_file.scene_count = 0
                existing_file.retry_count = 0
                existing_file.last_error = None
                modified_files.append(existing_file)
                changes_made = True

            if item.name != existing_file.file_name:
                existing_file.file_name = item.name
                metadata_updates.append({"video_id": existing_file.video_id, "video_title": item.name})
                changes_made = True

            if item.drive_path and item.drive_path != existing_file.drive_path:
                existing_file.drive_path = item.drive_path
                metadata_updates.append({"video_id": existing_file.video_id, "source_path": item.drive_path})
                changes_made = True

            if item.web_view_link and item.web_view_link != existing_file.web_view_link:
                existing_file.web_view_link = item.web_view_link
                changes_made = True

            if changes_made:
                updated_count += 1
            else:
                unchanged_count += 1
            continue

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
            web_view_link=item.web_view_link,
            video_id=video_id,
            processing_status="pending",
            enrichment_state="pending",
            stt_status="pending",
            ocr_status="pending",
        )
        db.add(drive_file)
        new_files.append(drive_file)
        created_count += 1

    if created_count > 0 or updated_count > 0:
        await db.flush()


    # SQS dual-write: publish processing jobs for newly created files.
    # Fire-and-forget — failures are logged but never block the DB commit.
    for f in new_files:
        publish_processing_job(
            file_id=f.id,
            org_id=org_id,
            connection_id=connection_id,
            video_id=f.video_id,
            google_file_id=f.google_file_id,
            file_name=f.file_name,
            mime_type=f.mime_type,
            file_size_bytes=f.file_size_bytes,
            library_id=connection.library_id,
            scope_type=connection.scope_type,
            drive_id=connection.drive_id,
        )

    for f in modified_files:
        publish_processing_job(
            file_id=f.id,
            org_id=org_id,
            connection_id=connection_id,
            video_id=f.video_id,
            google_file_id=f.google_file_id,
            file_name=f.file_name,
            mime_type=f.mime_type,
            file_size_bytes=f.file_size_bytes,
            library_id=connection.library_id,
            scope_type=connection.scope_type,
            drive_id=connection.drive_id,
        )

    latency_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "internal_sync_files_upserted",
        connection_id=str(connection_id),
        created_count=created_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        metadata_updates_count=len(metadata_updates),
        total_items=len(request.items),
        latency_ms=latency_ms,
        lease_token=_mask_lease_token(request.lease_token),
    )

    enqueued_jobs: dict[str, int] = {}
    if created_count + len(modified_files) > 0:
        enqueued_jobs = {"processing": created_count + len(modified_files)}

    return UpsertFilesResponse(
        created_count=created_count,
        updated_count=updated_count,
        unchanged_count=unchanged_count,
        enqueued_jobs=enqueued_jobs,
        metadata_updates=metadata_updates,
    )


@router.get(
    "/connections/{connection_id}/file_ids",
    response_model=ConnectionFileIdsResponse,
)
async def list_connection_file_ids(
    connection_id: UUID,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
):
    conn_result = await db.execute(
        select(DriveConnection).where(DriveConnection.id == connection_id)
    )
    connection = conn_result.scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")

    file_ids_result = await db.execute(
        select(DriveFile.google_file_id).where(
            DriveFile.connection_id == connection_id,
            DriveFile.org_id == connection.org_id,
            DriveFile.is_deleted.is_(False),
        )
    )
    google_file_ids = [row[0] for row in file_ids_result.all()]
    return ConnectionFileIdsResponse(
        google_file_ids=google_file_ids,
        total_count=len(google_file_ids),
    )


@router.patch(
    "/connections/{connection_id}/update_metadata",
    response_model=UpdateMetadataResponse,
)
async def update_metadata(
    connection_id: UUID,
    request: UpdateMetadataRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    conn_result = await db.execute(
        select(DriveConnection).where(DriveConnection.id == connection_id)
    )
    connection = conn_result.scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")
    _enforce_connection_lease(connection, request.lease_token)

    if not request.updates:
        return UpdateMetadataResponse(updated_scene_count=0, skipped_count=0)

    merged_updates: dict[str, dict[str, str]] = {}
    for update_item in request.updates:
        merged = merged_updates.setdefault(update_item.video_id, {})
        if update_item.video_title is not None:
            merged["video_title"] = update_item.video_title
        if update_item.source_path is not None:
            merged["source_path"] = update_item.source_path

    partial_updates: list[tuple[str, dict[str, str]]] = []
    skipped_count = 0
    org_id_str = str(connection.org_id)
    for video_id, fields in merged_updates.items():
        if not fields:
            skipped_count += 1
            continue

        scene_ids = await scene_client.find_scene_ids_by_video_id(org_id_str, video_id)
        if not scene_ids:
            skipped_count += 1
            continue

        for scene_id in scene_ids:
            partial_updates.append((scene_id, fields))

    if partial_updates:
        await scene_client.bulk_partial_update_scenes(partial_updates)

    return UpdateMetadataResponse(
        updated_scene_count=len(partial_updates),
        skipped_count=skipped_count,
    )


@router.post(
    "/connections/{connection_id}/delete_files",
    response_model=DeleteFilesResponse,
)
async def delete_files(
    connection_id: UUID,
    request: DeleteFilesRequest,
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    """Soft-delete files by Google file IDs. Removes scenes from OpenSearch."""
    conn_result = await db.execute(
        select(DriveConnection).where(DriveConnection.id == connection_id)
    )
    connection = conn_result.scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail=f"Connection not found: {connection_id}")
    _enforce_connection_lease(connection, request.lease_token)

    org_id = connection.org_id

    result = await db.execute(
        select(DriveFile).where(
            DriveFile.org_id == org_id,
            DriveFile.google_file_id.in_(request.google_file_ids),
            DriveFile.is_deleted.is_(False),
        )
    )
    files_to_delete = result.scalars().all()

    found_ids = {f.google_file_id for f in files_to_delete}
    not_found_count = len(request.google_file_ids) - len(found_ids)

    if files_to_delete:
        video_ids = list({f.video_id for f in files_to_delete})
        await db.execute(
            update(DriveFile)
            .where(
                DriveFile.org_id == org_id,
                DriveFile.google_file_id.in_(list(found_ids)),
                DriveFile.is_deleted.is_(False),
            )
            .values(is_deleted=True, deleted_at=func.now(), processing_status="deleted")
        )
        await db.flush()

        for vid in video_ids:
            try:
                await scene_client.delete_scenes_by_video_id(str(org_id), vid)
            except Exception:
                logger.warning("delete_scenes_from_opensearch_failed", extra={"video_id": vid})

    return DeleteFilesResponse(
        deleted_count=len(files_to_delete),
        not_found_count=not_found_count,
    )
