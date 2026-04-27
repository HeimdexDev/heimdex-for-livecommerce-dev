import logging
import time
import importlib
from typing import Any

from heimdex_worker_sdk import emit_event

logger = logging.getLogger(__name__)
_SERVICE_NAME = "youtube-worker"

_youtube_keys = importlib.import_module("heimdex_worker_sdk.youtube_keys")
youtube_metadata_s3_key = _youtube_keys.youtube_metadata_s3_key
youtube_original_s3_key = _youtube_keys.youtube_original_s3_key
youtube_subtitle_s3_key = _youtube_keys.youtube_subtitle_s3_key
S3Client = importlib.import_module("heimdex_worker_sdk.s3").S3Client


def _call_api(api_client: Any, candidates: list[str], *args: Any, **kwargs: Any) -> Any:
    for name in candidates:
        method = getattr(api_client, name, None)
        if callable(method):
            return method(*args, **kwargs)
    raise AttributeError(f"Missing API method; tried: {', '.join(candidates)}")


def cleanup_completed_videos(api_client: Any, settings: Any) -> int:
    videos = _call_api(
        api_client,
        ["list_youtube_cleanup_candidates", "list_completed_youtube_videos"],
    )
    s3 = S3Client(bucket=settings.drive_s3_bucket)
    deleted_count = 0

    for video in videos:
        if not video.get("all_enrichment_complete", True):
            logger.info("youtube_cleanup_skipped_incomplete", extra={"video_id": video.get("video_id")})
            emit_event(
                service=_SERVICE_NAME,
                event_name="youtube_skipped",
                category="job_failure",
                level="WARNING",
                duration_ms=0,
                message="enrichment_incomplete",
                metadata={
                    "mode": "cleanup_video",
                    "video_id": video.get("video_id"),
                    "youtube_video_id": video.get("youtube_video_id"),
                    "reason": "enrichment_incomplete",
                    "error_class": "EnrichmentIncomplete",
                },
            )
            continue
        if video.get("original_deleted"):
            continue

        org_id = str(video["org_id"])
        channel_ext_id = str(video.get("channel_external_id") or video.get("channel_id"))
        youtube_video = str(video["youtube_video_id"])
        video_pk = video["id"]

        t_start = time.monotonic()

        try:
            s3.delete(youtube_original_s3_key(org_id, channel_ext_id, youtube_video))
            s3.delete(youtube_subtitle_s3_key(org_id, channel_ext_id, youtube_video))
            s3.delete(youtube_metadata_s3_key(org_id, channel_ext_id, youtube_video))
            _call_api(
                api_client,
                ["mark_youtube_original_deleted", "update_youtube_original_deleted"],
                video_pk,
                original_deleted=True,
                org_id=org_id,
            )
            deleted_count += 1
            logger.info(
                "youtube_original_cleanup_complete",
                extra={"video_id": video.get("video_id"), "youtube_video_id": youtube_video},
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="youtube_completed",
                category="job_success",
                level="INFO",
                duration_ms=int((time.monotonic() - t_start) * 1000),
                metadata={
                    "mode": "cleanup_video",
                    "org_id_str": org_id,
                    "video_id": video.get("video_id"),
                    "youtube_video_id": youtube_video,
                    "channel_external_id": channel_ext_id,
                },
            )
        except Exception as e:
            logger.exception(
                "youtube_original_cleanup_failed",
                extra={"video_id": video.get("video_id"), "youtube_video_id": youtube_video},
            )
            emit_event(
                service=_SERVICE_NAME,
                event_name="youtube_failed",
                category="job_failure",
                level="ERROR",
                duration_ms=int((time.monotonic() - t_start) * 1000),
                message=f"{type(e).__name__}: {e}"[:1000],
                metadata={
                    "mode": "cleanup_video",
                    "org_id_str": org_id,
                    "video_id": video.get("video_id"),
                    "youtube_video_id": youtube_video,
                    "channel_external_id": channel_ext_id,
                    "error_class": type(e).__name__,
                    "error_msg": str(e)[:500],
                },
            )
    return deleted_count
