import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _decrypt_secret(encrypted_value: bytes, nonce: bytes, encryption_key_hex: str) -> dict[str, Any]:
    import json
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = bytes.fromhex(encryption_key_hex)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, encrypted_value, None)
    return json.loads(plaintext.decode())


def _parse_google_time(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def discover_new_files(session: AsyncSession, settings: Any) -> int:
    import app.db.models  # noqa: F401 — register all SQLAlchemy models for FK resolution
    from app.modules.drive.google_client import DriveClient
    from heimdex_worker_sdk.drive_keys import drive_video_id
    from app.modules.drive.models import DriveFile
    from app.modules.drive.repository import (
        DriveConnectionRepository,
        DriveFileRepository,
        DriveSecretRepository,
    )

    conn_repo = DriveConnectionRepository(session)
    file_repo = DriveFileRepository(session)
    secret_repo = DriveSecretRepository(session)

    active_connections = await conn_repo.get_active_connections()
    if not active_connections:
        return 0

    discovered_count = 0

    for connection in active_connections:
        org_id = connection.org_id
        org_id_str = str(org_id)
        scope_type = getattr(connection, "scope_type", "drive") or "drive"

        try:
            if scope_type == "folder":
                count = await _discover_folder_connection(
                    session, connection, file_repo, secret_repo, settings,
                )
            else:
                count = await _discover_drive_connection(
                    session, connection, file_repo, secret_repo, settings,
                )
            discovered_count += count

            connection.last_sync_at = func.now()
            connection.sync_requested_at = None
            await session.flush()
            logger.info(
                "discover_connection_complete",
                extra={
                    "org_id": org_id_str,
                    "connection_id": str(connection.id),
                    "scope_type": scope_type,
                    "drive_id": connection.drive_id,
                    "folder_id": getattr(connection, "folder_id", None),
                    "discovered": count,
                },
            )
        except Exception:
            logger.exception(
                "discover_connection_failed",
                extra={
                    "org_id": org_id_str,
                    "connection_id": str(connection.id),
                    "scope_type": scope_type,
                    "drive_id": connection.drive_id,
                    "folder_id": getattr(connection, "folder_id", None),
                },
            )

    return discovered_count


async def _discover_drive_connection(
    session: AsyncSession,
    connection: Any,
    file_repo: Any,
    secret_repo: Any,
    settings: Any,
) -> int:
    """Discover files from a Shared Drive connection (existing SA+DWD flow)."""
    from app.modules.drive.google_client import DriveClient
    from heimdex_worker_sdk.drive_keys import drive_video_id
    from app.modules.drive.models import DriveFile

    org_id = connection.org_id
    org_id_str = str(org_id)

    secret = await secret_repo.get_by_org(org_id, secret_type="service_account_key")
    if not secret:
        logger.warning(
            "discover_missing_secret",
            extra={"org_id": org_id_str, "connection_id": str(connection.id)},
        )
        connection.last_sync_at = func.now()
        connection.sync_requested_at = None
        await session.flush()
        return 0

    sa_key_info = _decrypt_secret(
        secret.encrypted_value,
        secret.nonce,
        settings.drive_sa_encryption_key,
    )
    drive_client = DriveClient(sa_key_info, secret.impersonate_email)

    discovered_count = 0
    page_token: str | None = None

    while True:
        response = drive_client.list_drive_files(
            connection.drive_id,
            page_token=page_token,
        )
        files = response.get("files", [])

        new_files: list[dict[str, Any]] = []
        for file in files:
            google_file_id = file.get("id")
            if not google_file_id:
                continue
            existing = await file_repo.get_by_google_file_id(org_id, google_file_id)
            if existing:
                continue
            new_files.append(file)

        path_map: dict[str, str] = {}
        if new_files:
            try:
                path_map = drive_client.resolve_folder_paths(
                    new_files, connection.drive_id,
                )
            except Exception:
                logger.warning(
                    "discover_path_resolve_failed",
                    extra={"org_id": org_id_str, "file_count": len(new_files)},
                    exc_info=True,
                )

        for file in new_files:
            google_file_id = file["id"]
            raw_size = file.get("size", 0)
            try:
                file_size_bytes = int(raw_size) or None
            except (TypeError, ValueError):
                file_size_bytes = None

            drive_file = DriveFile(
                org_id=org_id,
                connection_id=connection.id,
                google_file_id=google_file_id,
                file_name=file.get("name", ""),
                mime_type=file.get("mimeType", "application/octet-stream"),
                file_size_bytes=file_size_bytes,
                md5_checksum=file.get("md5Checksum"),
                google_modified_time=_parse_google_time(file.get("modifiedTime")),
                google_created_time=_parse_google_time(file.get("createdTime")),
                drive_path=path_map.get(google_file_id),
                video_id=drive_video_id(org_id_str, google_file_id),
                processing_status="pending",
                enrichment_state="pending",
                stt_status="pending",
                ocr_status="pending",
            )
            await file_repo.create(drive_file)
            discovered_count += 1

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return discovered_count


async def _discover_folder_connection(
    session: AsyncSession,
    connection: Any,
    file_repo: Any,
    secret_repo: Any,
    settings: Any,
) -> int:
    """Discover video files from a folder-scoped OAuth connection (recursive)."""
    from app.modules.drive.google_client import DriveClient
    from heimdex_worker_sdk.drive_keys import drive_video_id
    from app.modules.drive.models import DriveFile

    org_id = connection.org_id
    org_id_str = str(org_id)
    folder_id = connection.folder_id

    if not folder_id:
        logger.warning(
            "discover_folder_missing_folder_id",
            extra={"org_id": org_id_str, "connection_id": str(connection.id)},
        )
        return 0

    secret = await secret_repo.get_by_org(org_id, secret_type="oauth_token")
    if not secret:
        logger.warning(
            "discover_missing_oauth_secret",
            extra={"org_id": org_id_str, "connection_id": str(connection.id)},
        )
        connection.last_sync_at = func.now()
        connection.sync_requested_at = None
        await session.flush()
        return 0

    token_data = _decrypt_secret(
        secret.encrypted_value,
        secret.nonce,
        settings.drive_sa_encryption_key,
    )
    drive_client = DriveClient.from_oauth_token(
        refresh_token=token_data["refresh_token"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
    )

    # Collect the root folder + all subfolder IDs for recursive scanning
    all_folder_ids = [folder_id]
    try:
        subfolder_ids = drive_client.list_subfolders(folder_id)
        all_folder_ids.extend(subfolder_ids)
    except Exception:
        logger.warning(
            "discover_subfolder_listing_failed",
            extra={"org_id": org_id_str, "folder_id": folder_id},
            exc_info=True,
        )

    logger.info(
        "discover_folder_scan_start",
        extra={
            "org_id": org_id_str,
            "connection_id": str(connection.id),
            "root_folder_id": folder_id,
            "total_folders": len(all_folder_ids),
        },
    )

    discovered_count = 0
    folder_path_prefix = connection.folder_path or connection.folder_name or ""

    for current_folder_id in all_folder_ids:
        page_token: str | None = None
        while True:
            response = drive_client.list_folder_files(
                current_folder_id,
                page_token=page_token,
            )
            files = response.get("files", [])

            for file in files:
                google_file_id = file.get("id")
                if not google_file_id:
                    continue
                existing = await file_repo.get_by_google_file_id(org_id, google_file_id)
                if existing:
                    continue

                raw_size = file.get("size", 0)
                try:
                    file_size_bytes = int(raw_size) or None
                except (TypeError, ValueError):
                    file_size_bytes = None

                file_name = file.get("name", "")
                drive_path = f"{folder_path_prefix}/{file_name}" if folder_path_prefix else file_name

                drive_file = DriveFile(
                    org_id=org_id,
                    connection_id=connection.id,
                    google_file_id=google_file_id,
                    file_name=file_name,
                    mime_type=file.get("mimeType", "application/octet-stream"),
                    file_size_bytes=file_size_bytes,
                    md5_checksum=file.get("md5Checksum"),
                    google_modified_time=_parse_google_time(file.get("modifiedTime")),
                    google_created_time=_parse_google_time(file.get("createdTime")),
                    drive_path=drive_path,
                    video_id=drive_video_id(org_id_str, google_file_id),
                    processing_status="pending",
                    enrichment_state="pending",
                    stt_status="pending",
                    ocr_status="pending",
                )
                await file_repo.create(drive_file)
                discovered_count += 1

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return discovered_count
