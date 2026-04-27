import importlib
import json
import logging
import shutil
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _safe_update_job_status(api_client: Any, video_id: str, file_id: Any, **kwargs: Any) -> None:
    if video_id.startswith("yt_"):
        return
    api_client.update_job_status(file_id, **kwargs)


def _get_audio_duration_seconds(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate if rate > 0 else 0.0


async def process_stt_pending_files(api_client: Any, settings: Any, stt_processor: Any = None) -> None:
    files = api_client.claim_jobs("stt", limit=1)

    for claimed_file in files:
        _process_single_stt(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            stt_processor=stt_processor,
        )


def _process_single_stt(
    api_client: Any,
    settings: Any,
    claimed_file: Any,
    stt_processor: Any = None,
    diarizer: Any = None,
    callback_mode: str = "enrich",
) -> None:
    drive_keys = importlib.import_module("heimdex_worker_sdk.drive_keys")
    scene_manifest_s3_key = drive_keys.scene_manifest_s3_key
    S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client

    org_id = claimed_file.org_id
    org_id_str = str(org_id)
    file_id = claimed_file.id
    lease_token = claimed_file.lease_token
    video_id = claimed_file.video_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"stt_{video_id}_"))

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)

        audio_path = temp_dir / "audio.wav"
        try:
            s3.download_file(claimed_file.audio_s3_key, audio_path)
        except Exception as e:
            error_msg = f"audio_download_failed: {type(e).__name__}: {e}"
            _safe_update_job_status(
                api_client, video_id, file_id, job_type="stt", status="failed", error=error_msg, lease_token=lease_token,
            )
            return

        audio_duration = _get_audio_duration_seconds(audio_path)
        if audio_duration > settings.drive_stt_max_audio_seconds:
            error_msg = (
                f"audio_too_long: {audio_duration:.0f}s exceeds "
                f"max {settings.drive_stt_max_audio_seconds}s"
            )
            logger.warning(
                "stt_audio_too_long",
                extra={
                    "org_id": org_id_str,
                    "video_id": video_id,
                    "audio_seconds": audio_duration,
                    "max_seconds": settings.drive_stt_max_audio_seconds,
                },
            )
            _safe_update_job_status(
                api_client, video_id, file_id, job_type="stt", status="failed", error=error_msg, lease_token=lease_token,
            )
            return

        # scene_split mode: no manifest needed — scenes are created later
        # by split_scenes() using the STT result we upload here.
        scenes: list[dict[str, Any]] = []
        if callback_mode != "scene_split":
            manifest_key = scene_manifest_s3_key(org_id_str, video_id)
            manifest_path = temp_dir / "scenes.json"
            try:
                s3.download_file(manifest_key, manifest_path)
            except Exception as e:
                error_msg = f"manifest_download_failed: {type(e).__name__}: {e}"
                _safe_update_job_status(
                    api_client, video_id, file_id, job_type="stt", status="failed", error=error_msg, lease_token=lease_token,
                )
                return

            manifest = json.loads(manifest_path.read_text())
            scenes = manifest.get("scenes", [])

            if not scenes:
                _safe_update_job_status(api_client, video_id, file_id, job_type="stt", status="done", lease_token=lease_token)
                return

        stt_started = time.monotonic()

        stt_mod = importlib.import_module("heimdex_media_pipelines.speech.stt")
        convert_to_speech_segments = stt_mod.convert_to_speech_segments

        if stt_processor is None:
            stt_processor = stt_mod.create_stt_processor(
                backend=settings.drive_stt_backend,
                model_name=settings.drive_stt_model,
                language=settings.drive_stt_language,
                device=settings.stt_device,
                compute_type=settings.stt_compute_type,
                beam_size=1,
                best_of=1,
            )

        transcript_segments = stt_processor.transcribe(audio_path)
        stt_duration_ms = int((time.monotonic() - stt_started) * 1000)

        diarization_duration_ms = 0
        if diarizer is not None and transcript_segments:
            diar_mod = importlib.import_module("heimdex_media_pipelines.speech.diarization")
            diar_started = time.monotonic()
            speaker_turns = diarizer.diarize(audio_path)
            diar_mod.assign_speakers_to_segments(transcript_segments, speaker_turns)
            diarization_duration_ms = int((time.monotonic() - diar_started) * 1000)

        # --- Branch by callback_mode ---
        if callback_mode == "scene_split":
            # Upload raw STT result to S3 for speech-aware scene splitting
            _handle_scene_split_callback(
                s3=s3,
                settings=settings,
                org_id_str=org_id_str,
                video_id=video_id,
                file_id=file_id,
                transcript_segments=transcript_segments,
                convert_to_speech_segments=convert_to_speech_segments,
                diarizer=diarizer,
                audio_duration=audio_duration,
                stt_duration_ms=stt_duration_ms,
                temp_dir=temp_dir,
            )
        else:
            # Legacy enrichment path — align segments to existing scenes
            if not transcript_segments:
                updated_scenes = _build_scenes_no_speech(scenes)
            else:
                speech_segments = convert_to_speech_segments(transcript_segments)
                updated_scenes = _align_segments_to_scenes(scenes, speech_segments, diarized=diarizer is not None)

            try:
                ingest_result = _post_enrich_to_api(
                    settings=settings,
                    org_id=org_id,
                    video_id=video_id,
                    scenes=updated_scenes,
                )
            except Exception as e:
                error_msg = f"stt_reingest_failed: {type(e).__name__}: {e}"
                _safe_update_job_status(
                    api_client, video_id, file_id, job_type="stt", status="failed", error=error_msg, lease_token=lease_token,
                )
                return

            _safe_update_job_status(api_client, video_id, file_id, job_type="stt", status="done", lease_token=lease_token)

            total_segment_count = sum(
                s.get("speech_segment_count", 0) for s in updated_scenes
            )
            total_transcript_chars = sum(
                len(s.get("transcript_raw", "")) for s in updated_scenes
            )

            logger.info(
                "stt_processing_complete",
                extra={
                    "org_id": org_id_str,
                    "video_id": video_id,
                    "audio_seconds": round(audio_duration, 1),
                    "model": settings.drive_stt_model,
                    "backend": settings.drive_stt_backend,
                    "stt_duration_ms": stt_duration_ms,
                    "diarization_duration_ms": diarization_duration_ms,
                    "diarization_enabled": diarizer is not None,
                    "scene_count": len(scenes),
                    "segment_count": total_segment_count,
                    "transcript_chars": total_transcript_chars,
                    "updated_count": ingest_result.get("updated_count", 0),
                },
            )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        if callback_mode == "scene_split":
            # Notify API to proceed without STT (visual-only fallback)
            _notify_stt_complete(settings, file_id, stt_result_s3_key=None)
            logger.exception(
                "stt_scene_split_failed_fallback",
                extra={"org_id": org_id_str, "video_id": video_id, "error": error_msg},
            )
        else:
            _safe_update_job_status(
                api_client, video_id, file_id, job_type="stt", status="failed", error=error_msg, lease_token=lease_token,
            )
            logger.exception(
                "stt_processing_failed",
                extra={"org_id": org_id_str, "video_id": video_id},
            )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _align_segments_to_scenes(
    scenes: list[dict[str, Any]],
    speech_segments: list[Any],
    diarized: bool = False,
) -> list[dict[str, Any]]:
    merge_mod = importlib.import_module("heimdex_media_contracts.scenes.merge")
    SceneBoundary = importlib.import_module(
        "heimdex_media_contracts.scenes.schemas"
    ).SceneBoundary

    boundaries = [
        SceneBoundary(
            scene_id=s["scene_id"],
            index=s["index"],
            start_ms=s["start_ms"],
            end_ms=s["end_ms"],
            keyframe_timestamp_ms=s.get("keyframe_timestamp_ms", 0),
        )
        for s in scenes
    ]

    assignment = merge_mod.assign_segments_to_scenes(boundaries, speech_segments)

    updated: list[dict[str, Any]] = []
    for scene_dict in scenes:
        scene_copy = dict(scene_dict)
        scene_id = scene_dict["scene_id"]
        assigned = assignment.get(scene_id, [])
        scene_copy["transcript_raw"] = merge_mod.aggregate_transcript(assigned)
        scene_copy["speech_segment_count"] = len(assigned)

        if diarized:
            scene_copy["speaker_transcript"] = merge_mod.aggregate_speaker_transcript(assigned)
            scene_copy["speaker_count"] = merge_mod.count_distinct_speakers(assigned)

        updated.append(scene_copy)

    return updated


def _build_scenes_no_speech(
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for scene_dict in scenes:
        scene_copy = dict(scene_dict)
        scene_copy["transcript_raw"] = ""
        scene_copy["speech_segment_count"] = 0
        updated.append(scene_copy)
    return updated


ENRICH_BATCH_SIZE = 200


def _post_enrich_to_api(
    settings: Any,
    org_id: Any,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    requests = importlib.import_module("requests")

    enrich_scenes = []
    for scene in scenes:
        entry: dict[str, Any] = {
            "scene_id": scene["scene_id"],
            "transcript_raw": scene.get("transcript_raw", ""),
            "speech_segment_count": scene.get("speech_segment_count", 0),
        }
        if "speaker_transcript" in scene:
            entry["speaker_transcript"] = scene["speaker_transcript"]
            entry["speaker_count"] = scene.get("speaker_count", 0)
        enrich_scenes.append(entry)

    api_base = settings.drive_api_base_url.rstrip("/")
    url = f"{api_base}/internal/ingest/enrich"
    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "X-Heimdex-Org-Id": str(org_id),
        "Content-Type": "application/json",
    }

    total_updated = 0
    for batch_start in range(0, len(enrich_scenes), ENRICH_BATCH_SIZE):
        batch = enrich_scenes[batch_start : batch_start + ENRICH_BATCH_SIZE]
        payload = {"video_id": video_id, "scenes": batch}

        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Internal enrich API returned {resp.status_code}: {resp.text[:500]}"
            )
        total_updated += resp.json().get("updated_count", 0)

    return {"updated_count": total_updated, "video_id": video_id}


def _handle_scene_split_callback(
    s3: Any,
    settings: Any,
    org_id_str: str,
    video_id: str,
    file_id: Any,
    transcript_segments: list[Any],
    convert_to_speech_segments: Any,
    diarizer: Any,
    audio_duration: float,
    stt_duration_ms: int,
    temp_dir: Path,
) -> None:
    """Upload STT result to S3 and notify API to proceed with scene splitting."""
    drive_keys = importlib.import_module("heimdex_worker_sdk.drive_keys")
    stt_result_s3_key_fn = drive_keys.stt_result_s3_key

    # Convert transcript segments to serializable dicts
    segments_out: list[dict[str, Any]] = []
    if transcript_segments:
        speech_segments = convert_to_speech_segments(transcript_segments)
        for seg in speech_segments:
            entry: dict[str, Any] = {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "confidence": getattr(seg, "confidence", 0.0),
            }
            speaker_id = getattr(seg, "speaker_id", None)
            if speaker_id is not None:
                entry["speaker_id"] = speaker_id
            segments_out.append(entry)

    stt_result = {
        "segments": segments_out,
        "model": settings.drive_stt_model,
        "language": settings.drive_stt_language,
        "diarized": diarizer is not None,
        "audio_duration_s": audio_duration,
    }

    stt_result_path = temp_dir / "stt_result.json"
    stt_result_path.write_text(json.dumps(stt_result, default=str, ensure_ascii=False))

    stt_key = stt_result_s3_key_fn(org_id_str, video_id)
    s3.upload_file(stt_result_path, stt_key, content_type="application/json")

    _notify_stt_complete(settings, file_id, stt_result_s3_key=stt_key)

    logger.info(
        "stt_scene_split_callback_complete",
        extra={
            "org_id": org_id_str,
            "video_id": video_id,
            "audio_seconds": round(audio_duration, 1),
            "stt_duration_ms": stt_duration_ms,
            "segment_count": len(segments_out),
            "stt_result_s3_key": stt_key,
        },
    )


def _notify_stt_complete(
    settings: Any,
    file_id: Any,
    stt_result_s3_key: str | None,
) -> None:
    """POST to API to transition file from awaiting_stt to awaiting_scene_split."""
    requests = importlib.import_module("requests")

    url = (
        f"{settings.drive_api_base_url.rstrip('/')}"
        f"/internal/drive/processing/{file_id}/status"
    )
    body: dict[str, Any] = {
        "status": "awaiting_scene_split",
    }
    if stt_result_s3_key is not None:
        body["stt_result_s3_key"] = stt_result_s3_key

    headers = {
        "Authorization": f"Bearer {settings.drive_internal_api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.patch(url, json=body, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"stt_complete_callback_failed {resp.status_code}: {resp.text[:500]}"
        )
