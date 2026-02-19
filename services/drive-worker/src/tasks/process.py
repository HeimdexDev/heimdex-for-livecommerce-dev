import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def process_pending_files(
    session: AsyncSession,
    settings: Any,
    acquire_slot: Callable,
    release_slot: Callable,
) -> None:
    from app.modules.drive.models import DriveConnection, DriveFile, DriveSecret
    from app.modules.drive.repository import DriveConnectionRepository, DriveFileRepository

    conn_repo = DriveConnectionRepository(session)
    file_repo = DriveFileRepository(session)

    active_connections = await conn_repo.get_active_connections()
    if not active_connections:
        return

    for connection in active_connections:
        org_id_str = str(connection.org_id)

        if not acquire_slot(org_id_str, settings):
            continue

        try:
            files = await file_repo.claim_pending_files(connection.org_id, limit=1)
            if not files:
                release_slot(org_id_str)
                continue

            drive_file = files[0]
            await _process_single_file(
                session=session,
                settings=settings,
                connection=connection,
                drive_file=drive_file,
                file_repo=file_repo,
            )
        except Exception as e:
            logger.exception("process_file_error", extra={"org_id": org_id_str})
            release_slot(org_id_str)
        else:
            release_slot(org_id_str)


async def _process_single_file(
    session: AsyncSession,
    settings: Any,
    connection: Any,
    drive_file: Any,
    file_repo: Any,
) -> None:
    from app.modules.drive.google_client import DriveClient
    from app.modules.drive.keys import proxy_s3_key, thumbnail_s3_prefix
    from app.modules.drive.models import DriveSecret
    from app.modules.drive.repository import DriveSecretRepository
    from app.modules.drive.transcode import make_transcode_decision, probe_video, transcode_to_proxy
    from app.storage.s3 import S3Client

    org_id_str = str(drive_file.org_id)
    temp_dir = Path(settings.drive_temp_dir) / org_id_str / str(drive_file.id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        secret_repo = DriveSecretRepository(session)
        secret = await secret_repo.get_by_org(drive_file.org_id)
        if not secret:
            await file_repo.mark_failed(drive_file.id, "No SA key configured for org")
            return

        sa_key_info = _decrypt_sa_key(secret.encrypted_value, secret.nonce, settings.drive_sa_encryption_key)
        drive_client = DriveClient(sa_key_info, secret.impersonate_email)

        original_path = temp_dir / f"original_{drive_file.google_file_id}"
        logger.info("download_started", extra={"file_id": drive_file.google_file_id, "file_name": drive_file.file_name})

        await file_repo.update_status(drive_file.id, "downloading")
        drive_client.download_file_with_resume(
            file_id=drive_file.google_file_id,
            dest_path=original_path,
            expected_md5=drive_file.md5_checksum,
        )

        await file_repo.update_status(drive_file.id, "transcoding")
        probe = probe_video(original_path)
        decision = make_transcode_decision(probe)

        if decision.should_transcode:
            proxy_path = temp_dir / "proxy.mp4"
            transcode_to_proxy(original_path, proxy_path, probe, decision)
        else:
            proxy_path = original_path
            logger.info("transcode_skipped", extra={"reason": decision.reason, "file_id": drive_file.google_file_id})

        s3 = S3Client(bucket=settings.drive_s3_bucket)
        s3.ensure_bucket()
        s3_key = proxy_s3_key(org_id_str, connection.drive_id, drive_file.google_file_id)
        s3.upload_file(proxy_path, s3_key, content_type="video/mp4")

        proxy_probe = probe_video(proxy_path) if decision.should_transcode else probe

        proxy_size = proxy_path.stat().st_size

        await file_repo.update_status(
            drive_file.id,
            "processing",
            proxy_s3_key=s3_key,
            proxy_size_bytes=proxy_size,
            proxy_duration_ms=proxy_probe.duration_ms,
            thumbnail_s3_prefix=thumbnail_s3_prefix(org_id_str, connection.drive_id, drive_file.google_file_id),
        )

        ingest_result = _post_scenes_to_api(
            settings=settings,
            org_id=drive_file.org_id,
            video_id=drive_file.video_id,
            video_title=drive_file.file_name,
            library_id=connection.library_id,
            duration_ms=proxy_probe.duration_ms,
            capture_time=drive_file.google_created_time,
        )

        await file_repo.update_status(
            drive_file.id,
            "indexed",
            scene_count=ingest_result["indexed_count"],
        )

        logger.info(
            "file_processing_complete",
            extra={
                "file_id": drive_file.google_file_id,
                "video_id": drive_file.video_id,
                "proxy_s3_key": s3_key,
                "proxy_size_bytes": proxy_size,
                "transcoded": decision.should_transcode,
                "indexed_count": ingest_result["indexed_count"],
            },
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("file_processing_failed", extra={"file_id": drive_file.google_file_id, "error": error_msg})

        if drive_file.retry_count + 1 >= drive_file.max_retries:
            await file_repo.mark_failed(drive_file.id, error_msg)
        else:
            await file_repo.increment_retry(drive_file.id, error_msg)

    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _post_scenes_to_api(
    settings: Any,
    org_id: UUID,
    video_id: str,
    video_title: str,
    library_id: UUID,
    duration_ms: int,
    capture_time: Optional["datetime"] = None,
) -> dict[str, Any]:
    import requests

    capture_iso = capture_time.isoformat() if capture_time else None

    payload = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id),
        "total_duration_ms": duration_ms,
        "scenes": [
            {
                "scene_id": f"{video_id}_scene_0",
                "index": 0,
                "start_ms": 0,
                "end_ms": duration_ms,
                "transcript_raw": "",
                "ocr_text_raw": "",
                "source_type": "gdrive",
                "capture_time": capture_iso,
            }
        ],
    }

    api_base = settings.drive_api_base_url.rstrip("/")
    url = f"{api_base}/internal/ingest/scenes"

    resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.drive_internal_api_key}",
            "X-Heimdex-Org-Id": str(org_id),
            "Content-Type": "application/json",
        },
        timeout=60,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Internal ingest API returned {resp.status_code}: {resp.text[:500]}"
        )

    return resp.json()


def _decrypt_sa_key(encrypted_value: bytes, nonce: bytes, encryption_key_hex: str) -> dict[str, Any]:
    """Decrypt AES-256-GCM encrypted SA key JSON."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = bytes.fromhex(encryption_key_hex)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, encrypted_value, None)
    return json.loads(plaintext)
