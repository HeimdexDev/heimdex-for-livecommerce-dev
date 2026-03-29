# pyright: reportMissingImports=false

"""Phase 2: Speech-aware scene splitting after STT completion.

Consumes ``scene_split.job_created`` messages from the processing queue.
Downloads proxy + STT result from S3, runs ``split_scenes()`` with speech
data, then completes the standard ingest pipeline (keyframes, assemble,
upload, ingest).

Falls back to visual-only splitting when STT is unavailable.
"""

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from heimdex_media_pipelines.scenes.assembler import assemble_scenes
from heimdex_media_pipelines.scenes.keyframe import extract_all_keyframes
from heimdex_media_pipelines.scenes.splitter import split_scenes
from heimdex_media_pipelines.transcoding import probe_video
from heimdex_worker_sdk.drive_keys import (
    enrichment_keyframe_s3_key,
    enrichment_keyframe_s3_prefix,
    scene_manifest_s3_key,
    thumbnail_s3_key,
    thumbnail_s3_prefix,
)
from heimdex_worker_sdk.internal_api import InternalAPIClient
from heimdex_worker_sdk.s3 import S3Client

logger = logging.getLogger(__name__)

INGEST_BATCH_SIZE = 200


def handle_scene_split(
    message: dict[str, Any],
    api_client: InternalAPIClient,
    settings: Any,
) -> None:
    """Phase 2 handler: run speech-aware scene detection and ingest."""
    file_id = str(message["file_id"])
    org_id = str(message["org_id"])
    video_id = str(message["video_id"])
    proxy_s3_key = str(message["proxy_s3_key"])
    stt_result_key = message.get("stt_result_s3_key")
    stt_available = bool(message.get("stt_available", False))
    audio_key = message.get("audio_s3_key")
    library_id = str(message.get("library_id", ""))
    file_name = str(message.get("file_name", video_id))
    google_created_time = message.get("google_created_time")
    google_modified_time = message.get("google_modified_time")

    temp_dir = Path(settings.drive_temp_dir) / org_id / f"scene_split_{video_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    logger.info("scene_split_started", extra={
        "file_id": file_id,
        "video_id": video_id,
        "stt_available": stt_available,
    })

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)

        # Download proxy
        proxy_path = temp_dir / "proxy.mp4"
        s3.download_file(proxy_s3_key, proxy_path)
        probe = probe_video(proxy_path)

        # Download STT result if available
        speech_segments = None
        stt_result_path = None
        if stt_available and stt_result_key:
            stt_local = temp_dir / "stt_result.json"
            try:
                s3.download_file(stt_result_key, stt_local)
                stt_data = json.loads(stt_local.read_text())
                speech_segments = stt_data.get("segments", [])
                stt_result_path = str(stt_local)
                logger.info("scene_split_stt_loaded", extra={
                    "video_id": video_id,
                    "segment_count": len(speech_segments),
                })
            except Exception:
                logger.warning("scene_split_stt_download_failed", extra={
                    "video_id": video_id,
                    "stt_result_s3_key": stt_result_key,
                }, exc_info=True)

        # Run speech-aware scene detection
        split_preset = getattr(settings, "drive_split_preset", "default")
        t0 = time.monotonic()
        scene_boundaries = split_scenes(
            video_path=str(proxy_path),
            video_id=video_id,
            speech_segments=speech_segments,
            preset=split_preset,
        )
        logger.info("scene_split_detection_complete", extra={
            "video_id": video_id,
            "scene_count": len(scene_boundaries),
            "speech_used": speech_segments is not None,
            "elapsed_s": round(time.monotonic() - t0, 3),
        })

        # Extract keyframes
        keyframe_dir = temp_dir / "keyframes"
        extract_all_keyframes(
            video_path=str(proxy_path),
            scenes=scene_boundaries,
            out_dir=str(keyframe_dir),
        )

        # Assemble scenes (with speech data for transcript alignment)
        scene_result = assemble_scenes(
            video_path=str(proxy_path),
            video_id=video_id,
            scene_boundaries=scene_boundaries,
            speech_result_path=stt_result_path,
            total_duration_ms=probe.duration_ms,
        )

        # Upload thumbnails + keyframes
        kf_prefix = enrichment_keyframe_s3_prefix(org_id, video_id)
        for scene_doc in scene_result.scenes:
            if not scene_doc.thumbnail_path:
                continue
            local_path = Path(scene_doc.thumbnail_path)
            if not local_path.is_file():
                continue
            thumb_key = thumbnail_s3_key(org_id, video_id, scene_doc.scene_id)
            s3.upload_file(local_path, thumb_key, content_type="image/jpeg")
            kf_key = enrichment_keyframe_s3_key(org_id, video_id, scene_doc.scene_id)
            s3.upload_file(local_path, kf_key, content_type="image/jpeg")

        # Upload scene manifest (for enrichment workers)
        if getattr(settings, "drive_enrichment_enabled", False):
            google_capture_time = google_created_time or google_modified_time
            manifest = {
                "video_id": video_id,
                "file_name": file_name,
                "library_id": library_id,
                "total_duration_ms": probe.duration_ms,
                "capture_time": google_capture_time,
                "scenes": [
                    {
                        "scene_id": s.scene_id,
                        "index": s.index,
                        "start_ms": s.start_ms,
                        "end_ms": s.end_ms,
                    }
                    for s in scene_result.scenes
                ],
            }
            manifest_key = scene_manifest_s3_key(org_id, video_id)
            manifest_path = temp_dir / "scenes.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False))
            s3.upload_file(manifest_path, manifest_key, content_type="application/json")

        # Build scene dicts for ingest
        google_capture_time = google_created_time or google_modified_time
        scenes = _build_ingest_scene_dicts(
            scene_docs=scene_result.scenes,
            source_type="gdrive",
            capture_time=google_capture_time,
        )

        # Ingest scenes (batched)
        indexed_count = _post_scenes_batched(
            settings=settings,
            org_id=org_id,
            video_id=video_id,
            video_title=file_name,
            library_id=library_id,
            duration_ms=probe.duration_ms,
            scenes=scenes,
        )

        # Report indexed
        api_client.update_processing_status(
            UUID(file_id),
            status="indexed",
            lease_token=None,
            scene_count=indexed_count,
            thumbnail_s3_prefix=thumbnail_s3_prefix(org_id, video_id),
            audio_s3_key=audio_key,
            keyframe_s3_prefix=kf_prefix,
        )

        logger.info("scene_split_complete", extra={
            "video_id": video_id,
            "scene_count": len(scene_result.scenes),
            "indexed_count": indexed_count,
            "speech_used": speech_segments is not None,
        })

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception("scene_split_failed", extra={
            "video_id": video_id, "error": error_msg,
        })
        try:
            api_client.update_processing_status(
                UUID(file_id),
                status="failed",
                lease_token=None,
                error=error_msg,
            )
        except Exception:
            logger.warning("scene_split_status_update_failed", exc_info=True)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _build_ingest_scene_dicts(
    scene_docs: list[Any],
    source_type: str,
    capture_time: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
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
            "web_view_link": None,
            "content_type": "video",
        })
    return result


def _post_scenes_batched(
    settings: Any,
    org_id: str,
    video_id: str,
    video_title: str,
    library_id: str,
    duration_ms: int,
    scenes: list[dict[str, Any]],
) -> int:
    if not scenes:
        return 0

    import requests

    total_indexed = 0
    for offset in range(0, len(scenes), INGEST_BATCH_SIZE):
        batch = scenes[offset:offset + INGEST_BATCH_SIZE]
        payload: dict[str, Any] = {
            "video_id": video_id,
            "video_title": video_title,
            "library_id": library_id,
            "total_duration_ms": duration_ms,
            "scenes": batch,
        }
        url = f"{settings.drive_api_base_url.rstrip('/')}/internal/ingest/scenes"
        headers = {
            "Authorization": f"Bearer {settings.drive_internal_api_key}",
            "Content-Type": "application/json",
            "X-Heimdex-Org-Id": org_id,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"ingest_scenes_failed {resp.status_code}: {resp.text[:500]}")
        indexed = int(resp.json().get("indexed_count", len(batch)))
        total_indexed += indexed

    return total_indexed
