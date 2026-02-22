import json
import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional
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
    import app.db.models  # noqa: F401 — register all SQLAlchemy models for FK resolution
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
    from app.modules.drive.keys import (
        audio_s3_key, enrichment_keyframe_s3_key, enrichment_keyframe_s3_prefix,
        proxy_s3_key, thumbnail_s3_key, thumbnail_s3_prefix,
    )
    from app.modules.drive.models import DriveSecret
    from app.modules.drive.repository import DriveSecretRepository
    from heimdex_media_pipelines.transcoding import make_transcode_decision, probe_video, transcode_to_proxy
    from heimdex_media_pipelines.scenes.detector import detect_scenes
    from heimdex_media_pipelines.scenes.keyframe import extract_all_keyframes
    from heimdex_media_pipelines.scenes.assembler import assemble_scenes
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
        budget_bytes = int(settings.drive_temp_disk_budget_gb * 1024 * 1024 * 1024)
        drive_client.download_file_with_resume(
            file_id=drive_file.google_file_id,
            dest_path=original_path,
            expected_md5=drive_file.md5_checksum,
            budget_bytes=budget_bytes,
        )

        await file_repo.update_status(drive_file.id, "transcoding")
        probe = probe_video(original_path)
        max_height = settings.drive_proxy_max_height
        max_bitrate_kbps = int(settings.drive_proxy_max_bitrate.rstrip("k"))
        decision = make_transcode_decision(probe, max_height=max_height, max_bitrate_kbps=max_bitrate_kbps)

        if decision.should_transcode:
            proxy_path = temp_dir / "proxy.mp4"
            transcode_to_proxy(
                original_path, proxy_path, probe, decision,
                max_height=max_height,
                preset=settings.drive_proxy_preset,
                crf=settings.drive_proxy_crf,
                max_bitrate=settings.drive_proxy_max_bitrate,
                bufsize=settings.drive_proxy_bufsize,
                audio_bitrate=settings.drive_proxy_audio_bitrate,
            )
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
            thumbnail_s3_prefix=thumbnail_s3_prefix(org_id_str, drive_file.video_id),
        )

        # Scene detection uses original (not proxy) for best-quality boundaries.
        t0 = time.monotonic()
        scene_boundaries = detect_scenes(
            video_path=str(original_path),
            video_id=drive_file.video_id,
        )
        logger.info(
            "scene_detection_complete",
            extra={
                "video_id": drive_file.video_id,
                "scene_count": len(scene_boundaries),
                "elapsed_s": round(time.monotonic() - t0, 3),
            },
        )

        keyframe_dir = temp_dir / "keyframes"
        keyframe_paths = extract_all_keyframes(
            video_path=str(original_path),
            scenes=scene_boundaries,
            out_dir=str(keyframe_dir),
        )

        scene_result = assemble_scenes(
            video_path=str(original_path),
            video_id=drive_file.video_id,
            scene_boundaries=scene_boundaries,
            total_duration_ms=proxy_probe.duration_ms,
        )

        for scene_doc in scene_result.scenes:
            if scene_doc.thumbnail_path and Path(scene_doc.thumbnail_path).is_file():
                thumb_key = thumbnail_s3_key(
                    org_id_str, drive_file.video_id, scene_doc.scene_id,
                )
                s3.upload_file(
                    Path(scene_doc.thumbnail_path), thumb_key,
                    content_type="image/jpeg",
                )

        enrichment_fields = _upload_enrichment_artifacts(
            s3=s3,
            original_path=original_path,
            scene_result=scene_result,
            org_id_str=org_id_str,
            video_id=drive_file.video_id,
            temp_dir=temp_dir,
            enabled=settings.drive_enrichment_enabled,
        )

        capture_iso = drive_file.google_created_time.isoformat() if drive_file.google_created_time else None
        scene_dicts = _build_ingest_scene_dicts(
            scene_result.scenes,
            source_type="gdrive",
            capture_time=capture_iso,
        )

        if settings.drive_enrichment_enabled:
            _upload_scene_manifest(
                s3=s3,
                org_id_str=org_id_str,
                video_id=drive_file.video_id,
                video_title=drive_file.file_name,
                library_id=connection.library_id,
                duration_ms=proxy_probe.duration_ms,
                scenes=scene_dicts,
                temp_dir=temp_dir,
            )

        ingest_result = _post_scenes_to_api(
            settings=settings,
            org_id=drive_file.org_id,
            video_id=drive_file.video_id,
            video_title=drive_file.file_name,
            library_id=connection.library_id,
            duration_ms=proxy_probe.duration_ms,
            scenes=scene_dicts,
            source_path=drive_file.drive_path,
        )

        await file_repo.update_status(
            drive_file.id,
            "indexed",
            scene_count=ingest_result["indexed_count"],
            **enrichment_fields,
        )

        logger.info(
            "file_processing_complete",
            extra={
                "file_id": drive_file.google_file_id,
                "video_id": drive_file.video_id,
                "proxy_s3_key": s3_key,
                "proxy_size_bytes": proxy_size,
                "transcoded": decision.should_transcode,
                "scene_count": len(scene_result.scenes),
                "indexed_count": ingest_result["indexed_count"],
                "enrichment_state": enrichment_fields.get("enrichment_state"),
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


def _upload_enrichment_artifacts(
    s3: Any,
    original_path: Path,
    scene_result: Any,
    org_id_str: str,
    video_id: str,
    temp_dir: Path,
    enabled: bool = False,
) -> dict[str, object]:
    if not enabled:
        return {}

    from app.modules.drive.keys import (
        audio_s3_key, enrichment_keyframe_s3_key, enrichment_keyframe_s3_prefix,
    )

    fields: dict[str, object] = {}

    audio_path = temp_dir / "audio.wav"
    t0 = time.monotonic()
    try:
        subprocess.run(
            [
                "ffmpeg", "-i", str(original_path),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                "-y", str(audio_path),
            ],
            capture_output=True,
            check=True,
            timeout=600,
        )
        audio_size = audio_path.stat().st_size
        a_key = audio_s3_key(org_id_str, video_id)
        s3.upload_file(audio_path, a_key, content_type="audio/wav")
        fields["audio_s3_key"] = a_key
        logger.info(
            "enrichment_audio_uploaded",
            extra={
                "video_id": video_id,
                "audio_s3_key": a_key,
                "audio_size_bytes": audio_size,
                "elapsed_s": round(time.monotonic() - t0, 3),
            },
        )
    except Exception:
        logger.warning(
            "enrichment_audio_extract_failed",
            extra={"video_id": video_id},
            exc_info=True,
        )

    kf_prefix = enrichment_keyframe_s3_prefix(org_id_str, video_id)
    kf_count = 0
    for scene_doc in scene_result.scenes:
        if scene_doc.thumbnail_path and Path(scene_doc.thumbnail_path).is_file():
            kf_key = enrichment_keyframe_s3_key(org_id_str, video_id, scene_doc.scene_id)
            try:
                s3.upload_file(
                    Path(scene_doc.thumbnail_path), kf_key,
                    content_type="image/jpeg",
                )
                kf_count += 1
            except Exception:
                logger.warning(
                    "enrichment_keyframe_upload_failed",
                    extra={"video_id": video_id, "scene_id": scene_doc.scene_id},
                    exc_info=True,
                )

    if kf_count > 0:
        fields["keyframe_s3_prefix"] = kf_prefix
        logger.info(
            "enrichment_keyframes_uploaded",
            extra={
                "video_id": video_id,
                "keyframe_s3_prefix": kf_prefix,
                "keyframe_count": kf_count,
            },
        )

    if fields:
        fields["enrichment_state"] = "pending"
        fields["stt_status"] = "pending" if "audio_s3_key" in fields else None
        fields["ocr_status"] = "pending" if "keyframe_s3_prefix" in fields else None

    return fields


def _upload_scene_manifest(
    s3: Any,
    org_id_str: str,
    video_id: str,
    video_title: str,
    library_id: UUID,
    duration_ms: int,
    scenes: List[dict[str, Any]],
    temp_dir: Path,
) -> None:
    from app.modules.drive.keys import scene_manifest_s3_key

    manifest = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id),
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }
    manifest_path = temp_dir / "scenes.json"
    manifest_path.write_text(json.dumps(manifest))
    key = scene_manifest_s3_key(org_id_str, video_id)
    s3.upload_file(manifest_path, key, content_type="application/json")
    logger.info(
        "scene_manifest_uploaded",
        extra={"video_id": video_id, "s3_key": key, "scene_count": len(scenes)},
    )


def _build_ingest_scene_dicts(
    scene_docs: List[Any],
    source_type: str = "gdrive",
    capture_time: Optional[str] = None,
) -> List[dict[str, Any]]:
    result: List[dict[str, Any]] = []
    for doc in scene_docs:
        result.append({
            "scene_id": doc.scene_id,
            "index": doc.index,
            "start_ms": doc.start_ms,
            "end_ms": doc.end_ms,
            "keyframe_timestamp_ms": doc.keyframe_timestamp_ms,
            "transcript_raw": doc.transcript_raw,
            "speech_segment_count": doc.speech_segment_count,
            "keyword_tags": doc.keyword_tags,
            "product_tags": doc.product_tags,
            "product_entities": doc.product_entities,
            "ocr_text_raw": doc.ocr_text_raw,
            "ocr_char_count": doc.ocr_char_count,
            "source_type": source_type,
            "capture_time": capture_time,
        })
    return result


def _post_scenes_to_api(
    settings: Any,
    org_id: UUID,
    video_id: str,
    video_title: str,
    library_id: UUID,
    duration_ms: int,
    scenes: List[dict[str, Any]],
    source_path: Optional[str] = None,
) -> dict[str, Any]:
    import requests

    payload: dict[str, Any] = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id),
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }
    if source_path is not None:
        payload["source_path"] = source_path

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
