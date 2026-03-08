# pyright: reportMissingModuleSource=false, reportMissingTypeArgument=false, reportArgumentType=false

import logging
import shutil
import time
import importlib
from pathlib import Path
from typing import Any

import yt_dlp

logger = logging.getLogger(__name__)

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


def _first_file(path: Path, pattern: str) -> Path | None:
    matches = sorted(path.glob(pattern))
    return matches[0] if matches else None


def _yt_options(temp_dir: Path, settings: Any) -> dict[str, Any]:
    return {
        "format": settings.youtube_download_format,
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ko", "ko-KR"],
        "writeinfojson": True,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "sleep_interval": settings.youtube_rate_limit_sleep,
        "max_sleep_interval": settings.youtube_rate_limit_max_sleep,
    }


def download_and_upload_video(api_client: Any, settings: Any, video_record: dict[str, Any]) -> bool:
    org_id = str(video_record["org_id"])
    channel_ext_id = str(video_record.get("channel_external_id") or video_record.get("channel_id"))
    youtube_video = str(video_record["youtube_video_id"])
    temp_dir = Path(settings.youtube_temp_dir) / org_id / youtube_video
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        _call_api(
            api_client,
            ["update_youtube_video_status", "mark_youtube_video_status"],
            video_record["id"],
            status="downloading",
            org_id=org_id,
        )

        ydl = yt_dlp.YoutubeDL(_yt_options(temp_dir, settings))  # type: ignore[arg-type]
        video_url = video_record.get("video_url") or f"https://www.youtube.com/watch?v={youtube_video}"
        ydl.extract_info(video_url, download=True)

        original_path = _first_file(temp_dir, "*.mp4")
        subtitle_path = _first_file(temp_dir, "*.ko.vtt") or _first_file(temp_dir, "*.ko-KR.vtt") or _first_file(temp_dir, "*.vtt")
        metadata_path = _first_file(temp_dir, "*.info.json") or _first_file(temp_dir, "*.json")

        if not original_path:
            raise RuntimeError("downloaded_video_missing")

        _call_api(
            api_client,
            ["update_youtube_video_status", "mark_youtube_video_status"],
            video_record["id"],
            status="uploading",
            org_id=org_id,
        )

        s3 = S3Client(bucket=settings.drive_s3_bucket)
        s3.ensure_bucket()
        tags = {"auto-delete-after": f"{settings.youtube_original_ttl_days}d"}

        original_key = youtube_original_s3_key(org_id, channel_ext_id, youtube_video)
        s3.upload_file(
            original_path,
            original_key,
            content_type="video/mp4",
            tags=tags,
        )

        subtitle_key = None
        if subtitle_path and subtitle_path.exists():
            subtitle_key = youtube_subtitle_s3_key(org_id, channel_ext_id, youtube_video)
            s3.upload_file(
                subtitle_path,
                subtitle_key,
                content_type="text/vtt",
                tags=tags,
            )

        metadata_key = None
        if metadata_path and metadata_path.exists():
            metadata_key = youtube_metadata_s3_key(org_id, channel_ext_id, youtube_video)
            s3.upload_file(
                metadata_path,
                metadata_key,
                content_type="application/json",
                tags=tags,
            )

        _call_api(
            api_client,
            ["publish_youtube_transcode_job", "enqueue_youtube_transcode"],
            {
                "video_id": video_record["video_id"],
                "org_id": org_id,
                "youtube_video_id": youtube_video,
                "original_s3_key": original_key,
                "subtitle_s3_key": subtitle_key,
                "metadata_s3_key": metadata_key,
                "has_subtitles": subtitle_key is not None,
            },
            org_id=org_id,
        )

        _call_api(
            api_client,
            ["update_youtube_video_status", "mark_youtube_video_status"],
            video_record["id"],
            status="transcoding",
            original_s3_key=original_key,
            subtitle_s3_key=subtitle_key,
            metadata_s3_key=metadata_key,
            org_id=org_id,
        )

        logger.info(
            "youtube_download_upload_complete",
            extra={
                "video_id": video_record["video_id"],
                "youtube_video_id": youtube_video,
                "has_subtitles": subtitle_key is not None,
            },
        )
        return True
    except Exception as exc:
        logger.exception(
            "youtube_download_upload_failed",
            extra={
                "video_id": video_record.get("video_id"),
                "youtube_video_id": youtube_video,
            },
        )
        _call_api(
            api_client,
            ["update_youtube_video_status", "mark_youtube_video_status"],
            video_record["id"],
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            org_id=org_id,
        )
        return False
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        time.sleep(settings.youtube_rate_limit_sleep)


def process_pending_downloads(api_client: Any, settings: Any) -> int:
    pending = _call_api(
        api_client,
        ["claim_pending_youtube_downloads", "list_pending_youtube_videos"],
        limit=settings.youtube_max_concurrent_downloads,
    )
    success_count = 0
    for record in pending:
        if download_and_upload_video(api_client, settings, record):
            success_count += 1
    return success_count
