# pyright: reportMissingImports=false

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import requests

from heimdex_media_pipelines.scenes.assembler import assemble_scenes
from heimdex_media_pipelines.scenes.keyframe import extract_all_keyframes
from heimdex_media_pipelines.scenes.splitter import split_scenes
from heimdex_media_pipelines.transcoding import probe_video
from heimdex_worker_sdk.drive_keys import (
    enrichment_keyframe_s3_key,
    enrichment_keyframe_s3_prefix,
    scene_manifest_s3_key,
    stt_result_s3_key as stt_result_s3_key_fn,
    thumbnail_s3_key,
    thumbnail_s3_prefix,
)
from heimdex_worker_sdk.internal_api import InternalAPIClient
from heimdex_worker_sdk.s3 import S3Client
from heimdex_worker_sdk.youtube_keys import (
    youtube_keyframe_s3_key,
    youtube_keyframe_s3_prefix,
    youtube_thumbnail_s3_key,
    youtube_thumbnail_s3_prefix,
)

logger = logging.getLogger(__name__)

INGEST_BATCH_SIZE = 200


def handle_resplit(
    message: dict[str, Any],
    api_client: InternalAPIClient,
    settings: Any,
) -> None:
    _ = api_client
    job_id = str(message.get("job_id", ""))
    org_id = str(message.get("org_id", ""))
    video_id = str(message.get("video_id", ""))
    source_type = str(message.get("source_type", ""))
    proxy_s3_key = str(message.get("proxy_s3_key", ""))
    library_id = str(message.get("library_id", ""))
    video_title = str(message.get("video_title", video_id))
    scene_params = message.get("scene_params") or {}

    if not all([job_id, org_id, video_id, source_type, proxy_s3_key, library_id]):
        raise RuntimeError(f"resplit_missing_required_fields: {json.dumps(message, default=str)[:1000]}")

    if source_type not in {"gdrive", "youtube"}:
        raise RuntimeError(f"unsupported_resplit_source_type: {source_type}")

    temp_dir = Path(settings.drive_temp_dir) / org_id / f"resplit_{job_id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = temp_dir / "proxy.mp4"
    keyframe_dir = temp_dir / "keyframes"

    logger.info(
        "resplit_started",
        extra={
            "job_id": job_id,
            "org_id": org_id,
            "video_id": video_id,
            "source_type": source_type,
            "proxy_s3_key": proxy_s3_key,
            "scene_params": scene_params,
        },
    )

    try:
        _patch_reprocess_status(
            settings=settings,
            video_id=video_id,
            job_id=job_id,
            status="processing",
        )

        s3 = S3Client(bucket=settings.drive_s3_bucket)
        s3.download_file(proxy_s3_key, proxy_path)

        probe = probe_video(proxy_path)

        # Load existing STT result from S3 if available
        use_speech = bool(scene_params.get("use_speech", True))
        split_preset = scene_params.get("split_preset")
        speech_segments = None
        stt_result_path = None
        if use_speech:
            stt_key = stt_result_s3_key_fn(org_id, video_id)
            stt_local = temp_dir / "stt_result.json"
            try:
                s3.download_file(stt_key, stt_local)
                stt_data = json.loads(stt_local.read_text())
                speech_segments = stt_data.get("segments", [])
                stt_result_path = str(stt_local)
                logger.info("resplit_stt_loaded", extra={
                    "video_id": video_id,
                    "segment_count": len(speech_segments),
                })
            except Exception:
                logger.info("resplit_no_stt_data", extra={"video_id": video_id})

        overrides = {
            "visual_threshold": float(scene_params.get("threshold", 0.3)),
            "min_scene_duration_ms": int(scene_params.get("min_scene_duration_ms", 500)),
            "max_scene_duration_ms": int(scene_params.get("max_scene_duration_ms", 45_000)),
        }
        scene_boundaries = split_scenes(
            video_path=str(proxy_path),
            video_id=video_id,
            speech_segments=speech_segments,
            preset=split_preset,
            overrides=overrides,
        )
        extract_all_keyframes(
            video_path=str(proxy_path),
            scenes=scene_boundaries,
            out_dir=str(keyframe_dir),
        )
        scene_result = assemble_scenes(
            video_path=str(proxy_path),
            video_id=video_id,
            scene_boundaries=scene_boundaries,
            speech_result_path=stt_result_path,
            total_duration_ms=probe.duration_ms,
        )

        uploaded_thumbnails, uploaded_keyframes = _upload_scene_images(
            s3=s3,
            org_id=org_id,
            video_id=video_id,
            source_type=source_type,
            scene_docs=scene_result.scenes,
        )

        deleted_count = _delete_video_scenes(
            settings=settings,
            org_id=org_id,
            video_id=video_id,
        )

        scenes = _build_ingest_scene_dicts(
            scene_docs=scene_result.scenes,
            source_type=source_type,
        )
        indexed_count = _post_scenes_batched(
            settings=settings,
            org_id=org_id,
            video_id=video_id,
            video_title=video_title,
            library_id=library_id,
            duration_ms=probe.duration_ms,
            scenes=scenes,
        )

        # The STT worker reads ``scenes.json`` from
        # ``scene_manifest_s3_key(org, video)`` to map whisper segments
        # onto scene boundaries. Resplit used to skip this upload —
        # which meant post-resplit STT wrote transcripts against the
        # PRE-resplit scene_ids, and all new scenes came back empty.
        # Bug surfaced 2026-04-24 on staging devorg after the full-
        # pipeline reprocess: every scene had transcript_raw='' and
        # speech_segment_count=0 even though the video-level STT
        # result existed on S3.
        _upload_scene_manifest(
            s3=s3,
            org_id_str=org_id,
            video_id=video_id,
            video_title=video_title,
            library_id=library_id,
            duration_ms=probe.duration_ms,
            scenes=scenes,
            temp_dir=temp_dir,
        )

        eff_keyframe_prefix = _keyframe_prefix(source_type, org_id, video_id)
        audio_s3_key = str(message.get("audio_s3_key", ""))

        _patch_reprocess_status(
            settings=settings,
            video_id=video_id,
            job_id=job_id,
            status="completed",
            scene_count=indexed_count,
            org_id=org_id,
            keyframe_s3_prefix=eff_keyframe_prefix,
            audio_s3_key=audio_s3_key,
        )

        logger.info(
            "resplit_completed",
            extra={
                "job_id": job_id,
                "org_id": org_id,
                "video_id": video_id,
                "deleted_scene_count": deleted_count,
                "indexed_scene_count": indexed_count,
                "uploaded_thumbnail_count": uploaded_thumbnails,
                "uploaded_keyframe_count": uploaded_keyframes,
                "thumbnail_s3_prefix": _thumbnail_prefix(source_type, org_id, video_id),
                "keyframe_s3_prefix": eff_keyframe_prefix,
            },
        )
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.exception(
            "resplit_failed",
            extra={
                "job_id": job_id,
                "org_id": org_id,
                "video_id": video_id,
                "error": error_msg,
            },
        )
        _patch_reprocess_status(
            settings=settings,
            video_id=video_id,
            job_id=job_id,
            status="failed",
            error=error_msg[:500],
        )
        raise
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _headers(settings: Any, org_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "Content-Type": "application/json",
    }
    if org_id is not None:
        headers["X-Heimdex-Org-Id"] = org_id
    return headers


def _patch_reprocess_status(
    settings: Any,
    video_id: str,
    job_id: str,
    status: str,
    scene_count: int | None = None,
    error: str | None = None,
    org_id: str | None = None,
    keyframe_s3_prefix: str | None = None,
    audio_s3_key: str | None = None,
) -> None:
    url = f"{settings.drive_api_base_url.rstrip('/')}/internal/videos/{video_id}/reprocess/{job_id}/status"
    body: dict[str, Any] = {"status": status}
    if scene_count is not None:
        body["scene_count"] = scene_count
    if error is not None:
        body["error"] = error
    if org_id is not None:
        body["org_id"] = org_id
    if keyframe_s3_prefix is not None:
        body["keyframe_s3_prefix"] = keyframe_s3_prefix
    if audio_s3_key is not None:
        body["audio_s3_key"] = audio_s3_key

    resp = requests.patch(
        url,
        json=body,
        headers=_headers(settings),
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"reprocess_status_update_failed {resp.status_code}: {resp.text[:500]}")


def _delete_video_scenes(settings: Any, org_id: str, video_id: str) -> int:
    url = f"{settings.drive_api_base_url.rstrip('/')}/internal/videos/{video_id}/scenes"
    resp = requests.delete(
        url,
        headers=_headers(settings, org_id),
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"delete_scenes_failed {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()
    return int(payload.get("deleted", 0))


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
        resp = requests.post(
            url,
            json=payload,
            headers=_headers(settings, org_id),
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"ingest_scenes_failed {resp.status_code}: {resp.text[:500]}")

        indexed = int(resp.json().get("indexed_count", len(batch)))
        total_indexed += indexed
        logger.info(
            "resplit_ingest_batch_complete",
            extra={
                "video_id": video_id,
                "batch_offset": offset,
                "batch_size": len(batch),
                "indexed_count": indexed,
            },
        )

    return total_indexed


def _upload_scene_manifest(
    s3: S3Client,
    org_id_str: str,
    video_id: str,
    video_title: str,
    library_id: str | None,
    duration_ms: int,
    scenes: list[dict[str, Any]],
    temp_dir: Path,
) -> None:
    """Write scenes.json to ``scene_manifest_s3_key``.

    Mirrors the transcode worker's helper. Same schema — total_duration_ms
    + scenes list of dicts carrying scene_id/index/start_ms/end_ms/
    keyframe_timestamp_ms. The STT worker reads only those fields;
    extra keys we write (tags, transcript_raw, etc.) are harmlessly
    ignored.
    """
    manifest = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id) if library_id else None,
        "total_duration_ms": duration_ms,
        "scenes": scenes,
    }
    manifest_path = temp_dir / "scenes.json"
    manifest_path.write_text(json.dumps(manifest))
    key = scene_manifest_s3_key(org_id_str, video_id)
    s3.upload_file(manifest_path, key, content_type="application/json")
    logger.info(
        "resplit_scene_manifest_uploaded",
        extra={"video_id": video_id, "s3_key": key, "scene_count": len(scenes)},
    )


def _build_ingest_scene_dicts(
    scene_docs: list[Any],
    source_type: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for doc in scene_docs:
        result.append(
            {
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
                "capture_time": None,
                "web_view_link": None,
                "content_type": "video",
            }
        )
    return result


def _thumbnail_prefix(source_type: str, org_id: str, video_id: str) -> str:
    if source_type == "youtube":
        return youtube_thumbnail_s3_prefix(org_id, video_id)
    return thumbnail_s3_prefix(org_id, video_id)


def _keyframe_prefix(source_type: str, org_id: str, video_id: str) -> str:
    if source_type == "youtube":
        return youtube_keyframe_s3_prefix(org_id, video_id)
    return enrichment_keyframe_s3_prefix(org_id, video_id)


def _upload_scene_images(
    s3: S3Client,
    org_id: str,
    video_id: str,
    source_type: str,
    scene_docs: list[Any],
) -> tuple[int, int]:
    thumbnail_count = 0
    keyframe_count = 0

    for scene_doc in scene_docs:
        if not scene_doc.thumbnail_path:
            continue
        local_path = Path(scene_doc.thumbnail_path)
        if not local_path.is_file():
            continue

        if source_type == "youtube":
            thumb_key = youtube_thumbnail_s3_key(org_id, video_id, scene_doc.scene_id)
            keyframe_key = youtube_keyframe_s3_key(org_id, video_id, scene_doc.scene_id)
        else:
            thumb_key = thumbnail_s3_key(org_id, video_id, scene_doc.scene_id)
            keyframe_key = enrichment_keyframe_s3_key(org_id, video_id, scene_doc.scene_id)

        s3.upload_file(local_path, thumb_key, content_type="image/jpeg")
        s3.upload_file(local_path, keyframe_key, content_type="image/jpeg")
        thumbnail_count += 1
        keyframe_count += 1

    return thumbnail_count, keyframe_count
