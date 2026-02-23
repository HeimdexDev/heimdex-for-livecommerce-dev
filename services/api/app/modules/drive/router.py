import logging
import os
from typing import Annotated
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository, DriveSecretRepository
from app.modules.drive.schemas import (
    DriveConnectionCreate,
    DriveConnectionResponse,
    DriveConnectionUpdate,
    DriveFileListResponse,
    DriveFileResponse,
    DriveFolderConnectionCreate,
    DriveFolderInfo,
    DriveFolderListResponse,
    DriveSecretCreate,
    DriveSecretResponse,
    DriveStatusResponse,
    SyncTriggerResponse,
)
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drive", tags=["drive"])
playback_router = APIRouter(prefix="/playback", tags=["playback"])


def _require_drive_enabled() -> None:
    if not get_settings().drive_connector_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drive connector is not enabled",
        )


PROCESSING_STATUSES = frozenset({"downloading", "transcoding", "processing"})


@router.get("/status", response_model=DriveStatusResponse)
async def get_status(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    settings = get_settings()
    if not settings.drive_connector_enabled:
        return DriveStatusResponse(connected=False)

    conn_repo = DriveConnectionRepository(db)
    file_repo = DriveFileRepository(db)

    connections = await conn_repo.list_by_org(org_ctx.org_id)
    active = next((c for c in connections if c.status == "active"), None)
    if not active:
        return DriveStatusResponse(connected=False)

    counts = await file_repo.count_by_status(org_ctx.org_id)
    last_indexed = await file_repo.latest_indexed_at(org_ctx.org_id)

    total = sum(counts.values())
    indexed = counts.get("indexed", 0)
    failed = counts.get("failed", 0)
    processing = sum(v for k, v in counts.items() if k in PROCESSING_STATUSES)
    pending = counts.get("pending", 0)

    return DriveStatusResponse(
        connected=True,
        connection_status=active.status,
        drive_name=active.drive_name,
        last_sync_at=active.last_sync_at,
        total_files=total,
        indexed=indexed,
        processing=processing,
        pending=pending,
        failed=failed,
        last_indexed_at=last_indexed,
    )


@router.get("/connections", response_model=list[DriveConnectionResponse])
async def list_connections(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    return await conn_repo.list_by_org(org_ctx.org_id)


@router.post("/connections", response_model=DriveConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: DriveConnectionCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    return await conn_repo.create(org_ctx.org_id, body)


@router.get("/connections/{connection_id}", response_model=DriveConnectionResponse)
async def get_connection(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    conn = await conn_repo.get_by_id(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


@router.post("/connections/{connection_id}/sync", response_model=SyncTriggerResponse)
async def trigger_sync(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    conn = await conn_repo.set_sync_requested(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    if conn.sync_requested_at is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Sync request failed")
    return SyncTriggerResponse(status="requested", sync_requested_at=conn.sync_requested_at)


@router.get("/connections/{connection_id}/folders", response_model=DriveFolderListResponse)
async def list_folders(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    file_repo = DriveFileRepository(db)
    conn = await conn_repo.get_by_id(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    folder_stats = await file_repo.get_folder_stats(connection_id, org_ctx.org_id)
    folders = [DriveFolderInfo(**f) for f in folder_stats]
    total_files = sum(f.file_count for f in folders)
    return DriveFolderListResponse(folders=folders, total_files=total_files)


@router.patch("/connections/{connection_id}", response_model=DriveConnectionResponse)
async def update_connection(
    connection_id: UUID,
    body: DriveConnectionUpdate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    conn = await conn_repo.update(connection_id, org_ctx.org_id, body)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return conn


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    conn_repo = DriveConnectionRepository(db)
    deleted = await conn_repo.delete(connection_id, org_ctx.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")


@router.get("/connections/{connection_id}/files", response_model=DriveFileListResponse)
async def list_files(
    connection_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
    processing_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    conn_repo = DriveConnectionRepository(db)
    file_repo = DriveFileRepository(db)
    conn = await conn_repo.get_by_id(connection_id, org_ctx.org_id)
    if conn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    files, total = await file_repo.list_by_connection(
        connection_id, org_ctx.org_id, processing_status=processing_status, limit=limit, offset=offset
    )
    return DriveFileListResponse(
        files=[DriveFileResponse.model_validate(f) for f in files],
        total=total,
    )


@router.get("/files/{file_id}", response_model=DriveFileResponse)
async def get_file(
    file_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    file_repo = DriveFileRepository(db)
    f = await file_repo.get_by_id(file_id, org_ctx.org_id)
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return f


@router.put("/secrets", response_model=DriveSecretResponse, status_code=status.HTTP_200_OK)
async def upsert_secret(
    body: DriveSecretCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    settings = get_settings()
    if not settings.drive_sa_encryption_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="DRIVE_SA_ENCRYPTION_KEY not configured",
        )
    key = bytes.fromhex(settings.drive_sa_encryption_key)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    encrypted_value = aesgcm.encrypt(nonce, body.sa_key_json.encode(), None)

    secret_repo = DriveSecretRepository(db)
    secret = await secret_repo.upsert(
        org_id=org_ctx.org_id,
        encrypted_value=encrypted_value,
        nonce=nonce,
        impersonate_email=body.impersonate_email,
    )
    return secret


@router.post("/folder-connections", response_model=DriveConnectionResponse, status_code=status.HTTP_201_CREATED)
async def create_folder_connection(
    body: DriveFolderConnectionCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
):
    settings = get_settings()
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Drive OAuth is not configured",
        )

    secret_repo = DriveSecretRepository(db)
    secret = await secret_repo.get_by_org(org_ctx.org_id, secret_type="oauth_token")
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Drive is not connected. Please connect via OAuth first.",
        )

    from app.modules.drive.models import DriveConnection

    conn = DriveConnection(
        org_id=org_ctx.org_id,
        library_id=body.library_id,
        scope_type="folder",
        drive_id=None,
        drive_name=None,
        folder_id=body.folder_id,
        folder_name=body.folder_name,
        folder_path=body.folder_path,
    )
    db.add(conn)
    await db.flush()
    await db.refresh(conn)
    return conn


@router.get("/browse-folders")
async def browse_folders(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_drive_enabled)],
    parent_id: str = "root",
):
    settings = get_settings()
    if not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Drive OAuth is not configured",
        )

    secret_repo = DriveSecretRepository(db)
    secret = await secret_repo.get_by_org(org_ctx.org_id, secret_type="oauth_token")
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Drive is not connected. Please connect via OAuth first.",
        )

    key = bytes.fromhex(settings.drive_sa_encryption_key)
    aesgcm = AESGCM(key)
    decrypted = aesgcm.decrypt(secret.nonce, secret.encrypted_value, None)

    import json
    token_data = json.loads(decrypted)

    from app.modules.drive.google_client import DriveClient
    drive_client = DriveClient.from_oauth_token(
        refresh_token=token_data["refresh_token"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
    )

    folders = drive_client.list_folders(parent_id)
    return {"folders": folders, "parent_id": parent_id}


_RANGE_CHUNK = 2 * 1024 * 1024


@playback_router.get("/{video_id}")
async def stream_playback(
    video_id: str,
    request: Request,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    if not video_id.startswith("gd_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Playback proxy is only available for drive videos",
        )

    settings = get_settings()
    if not settings.drive_connector_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drive connector is not enabled",
        )

    file_repo = DriveFileRepository(db)
    drive_file = await file_repo.get_by_video_id(org_ctx.org_id, video_id)
    if drive_file is None or not drive_file.proxy_s3_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video proxy not found",
        )

    from app.storage.s3 import S3Client

    s3 = S3Client(bucket=settings.drive_s3_bucket)

    try:
        head = s3._client.head_object(Bucket=s3.bucket, Key=drive_file.proxy_s3_key)
    except Exception:
        logger.warning("playback_head_failed", extra={"key": drive_file.proxy_s3_key}, exc_info=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Video proxy not found")

    total_size = head["ContentLength"]
    content_type = head.get("ContentType", "video/mp4")

    range_header = request.headers.get("range")

    if range_header:
        # RFC 7233: Range = "bytes" "=" byte-range-set
        range_spec = range_header.strip().lower()
        if not range_spec.startswith("bytes="):
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)

        range_val = range_spec[6:]
        parts = range_val.split("-", 1)
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else min(start + _RANGE_CHUNK - 1, total_size - 1)
        end = min(end, total_size - 1)

        if start >= total_size or start > end:
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)

        content_length = end - start + 1

        def _range_iter():
            resp = s3._client.get_object(
                Bucket=s3.bucket,
                Key=drive_file.proxy_s3_key,
                Range=f"bytes={start}-{end}",
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
                "Cache-Control": "public, max-age=3600",
            },
        )

    def _full_iter():
        resp = s3._client.get_object(Bucket=s3.bucket, Key=drive_file.proxy_s3_key)
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
            "Cache-Control": "public, max-age=3600",
        },
    )
