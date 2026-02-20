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


def _get_audio_duration_seconds(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / rate if rate > 0 else 0.0


async def process_stt_pending_files(session: Any, settings: Any, stt_processor: Any = None) -> None:
    import app.db.models  # noqa: F401 — register all SQLAlchemy models for FK resolution
    drive_repository = importlib.import_module("app.modules.drive.repository")
    file_repo = drive_repository.DriveFileRepository(session)
    files = await file_repo.claim_stt_pending_files(limit=1)

    for drive_file in files:
        await _process_single_stt(
            session=session,
            settings=settings,
            drive_file=drive_file,
            file_repo=file_repo,
            stt_processor=stt_processor,
        )


async def _process_single_stt(
    session: Any,
    settings: Any,
    drive_file: Any,
    file_repo: Any,
    stt_processor: Any = None,
) -> None:
    drive_keys = importlib.import_module("app.modules.drive.keys")
    scene_manifest_s3_key = drive_keys.scene_manifest_s3_key
    S3Client = importlib.import_module("app.storage.s3").S3Client

    _ = session
    org_id = drive_file.org_id
    org_id_str = str(org_id)
    video_id = drive_file.video_id
    temp_dir = Path(tempfile.mkdtemp(prefix=f"stt_{video_id}_"))

    try:
        s3 = S3Client(bucket=settings.drive_s3_bucket)

        audio_path = temp_dir / "audio.wav"
        try:
            s3.download_file(drive_file.audio_s3_key, audio_path)
        except Exception as e:
            error_msg = f"audio_download_failed: {type(e).__name__}: {e}"
            await file_repo.update_stt_enrichment_status(
                drive_file.id,
                stt_status="failed",
                enrichment_error=error_msg,
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
            await file_repo.update_stt_enrichment_status(
                drive_file.id,
                stt_status="failed",
                enrichment_error=error_msg,
            )
            return

        manifest_key = scene_manifest_s3_key(org_id_str, video_id)
        manifest_path = temp_dir / "scenes.json"
        try:
            s3.download_file(manifest_key, manifest_path)
        except Exception as e:
            error_msg = f"manifest_download_failed: {type(e).__name__}: {e}"
            await file_repo.update_stt_enrichment_status(
                drive_file.id,
                stt_status="failed",
                enrichment_error=error_msg,
            )
            return

        manifest = json.loads(manifest_path.read_text())
        scenes = manifest.get("scenes", [])

        if not scenes:
            await file_repo.update_stt_enrichment_status(
                drive_file.id, stt_status="done",
            )
            return

        stt_started = time.monotonic()

        stt_mod = importlib.import_module("heimdex_media_pipelines.speech.stt")
        convert_to_speech_segments = stt_mod.convert_to_speech_segments

        if stt_processor is None:
            stt_processor = stt_mod.create_stt_processor(
                backend=settings.drive_stt_backend,
                model_name=settings.drive_stt_model,
                language=settings.drive_stt_language,
                device="cpu",
                compute_type="int8",
                beam_size=1,
                best_of=1,
            )

        transcript_segments = stt_processor.transcribe(audio_path)
        stt_duration_ms = int((time.monotonic() - stt_started) * 1000)

        if not transcript_segments:
            updated_scenes = _build_scenes_no_speech(scenes)
        else:
            speech_segments = convert_to_speech_segments(transcript_segments)
            updated_scenes = _align_segments_to_scenes(scenes, speech_segments)

        video_title = manifest.get(
            "video_title", getattr(drive_file, "file_name", ""),
        )
        library_id = manifest.get(
            "library_id", getattr(drive_file, "library_id", None),
        )
        duration_ms = manifest.get(
            "total_duration_ms", getattr(drive_file, "proxy_duration_ms", 0),
        )

        try:
            ingest_result = _post_scenes_to_api(
                settings=settings,
                org_id=org_id,
                video_id=video_id,
                video_title=video_title,
                library_id=library_id,
                duration_ms=duration_ms,
                scenes=updated_scenes,
            )
        except Exception as e:
            error_msg = f"stt_reingest_failed: {type(e).__name__}: {e}"
            await file_repo.update_stt_enrichment_status(
                drive_file.id,
                stt_status="failed",
                enrichment_error=error_msg,
            )
            return

        await file_repo.update_stt_enrichment_status(
            drive_file.id, stt_status="done",
        )

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
                "scene_count": len(scenes),
                "segment_count": total_segment_count,
                "transcript_chars": total_transcript_chars,
                "indexed_count": ingest_result.get("indexed_count", 0),
            },
        )

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        await file_repo.update_stt_enrichment_status(
            drive_file.id,
            stt_status="failed",
            enrichment_error=error_msg,
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
) -> list[dict[str, Any]]:
    SceneBoundary = importlib.import_module(
        "heimdex_media_contracts.scenes.schemas"
    ).SceneBoundary
    assign_segments_to_scenes = importlib.import_module(
        "heimdex_media_contracts.scenes.merge"
    ).assign_segments_to_scenes
    aggregate_transcript = importlib.import_module(
        "heimdex_media_contracts.scenes.merge"
    ).aggregate_transcript

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

    assignment = assign_segments_to_scenes(boundaries, speech_segments)

    updated: list[dict[str, Any]] = []
    for scene_dict in scenes:
        scene_copy = dict(scene_dict)
        scene_id = scene_dict["scene_id"]
        assigned = assignment.get(scene_id, [])
        transcript_raw = aggregate_transcript(assigned)
        scene_copy["transcript_raw"] = transcript_raw
        scene_copy["speech_segment_count"] = len(assigned)
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


def _post_scenes_to_api(
    settings: Any,
    org_id: Any,
    video_id: str,
    video_title: str,
    library_id: Any,
    duration_ms: int,
    scenes: list[dict[str, Any]],
) -> dict[str, Any]:
    requests = importlib.import_module("requests")

    payload = {
        "video_id": video_id,
        "video_title": video_title,
        "library_id": str(library_id),
        "total_duration_ms": duration_ms,
        "scenes": scenes,
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
        timeout=120,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Internal ingest API returned {resp.status_code}: {resp.text[:500]}"
        )

    return resp.json()
