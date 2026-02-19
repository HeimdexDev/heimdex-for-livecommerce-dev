import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _decrypt_sa_key(encrypted_value: bytes, nonce: bytes, encryption_key_hex: str) -> dict[str, Any]:
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
    from app.modules.drive.keys import drive_video_id
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
        page_token: str | None = None

        try:
            secret = await secret_repo.get_by_org(org_id)
            if not secret:
                logger.warning(
                    "discover_missing_secret",
                    extra={"org_id": org_id_str, "connection_id": str(connection.id)},
                )
                connection.last_sync_at = func.now()
                await session.flush()
                continue

            sa_key_info = _decrypt_sa_key(
                secret.encrypted_value,
                secret.nonce,
                settings.drive_sa_encryption_key,
            )
            drive_client = DriveClient(sa_key_info, secret.impersonate_email)

            while True:
                response = drive_client.list_drive_files(
                    connection.drive_id,
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

            connection.last_sync_at = func.now()
            await session.flush()
            logger.info(
                "discover_connection_complete",
                extra={
                    "org_id": org_id_str,
                    "connection_id": str(connection.id),
                    "drive_id": connection.drive_id,
                },
            )
        except Exception:
            logger.exception(
                "discover_connection_failed",
                extra={
                    "org_id": org_id_str,
                    "connection_id": str(connection.id),
                    "drive_id": connection.drive_id,
                },
            )

    return discovered_count
