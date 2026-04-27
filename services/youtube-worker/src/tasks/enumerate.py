# pyright: reportMissingModuleSource=false, reportMissingTypeArgument=false, reportArgumentType=false

import logging
import importlib
from typing import Any

import yt_dlp

logger = logging.getLogger(__name__)
youtube_video_id = importlib.import_module("heimdex_worker_sdk.youtube_keys").youtube_video_id


def _videos_tab_url(channel_url: str) -> str:
    url = channel_url.rstrip("/")
    if url.endswith("/videos"):
        return url
    return f"{url}/videos"


def enumerate_channel(channel_url: str, cookies_path: str | None = None) -> list[dict[str, Any]]:
    url = _videos_tab_url(channel_url)
    options: dict[str, Any] = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
    }
    if cookies_path:
        options["cookiefile"] = cookies_path
    ydl = yt_dlp.YoutubeDL(options)  # type: ignore[arg-type]
    info = ydl.extract_info(url, download=False) or {}

    entries = info.get("entries") or []
    results: list[dict[str, Any]] = []
    for entry in entries:
        if not entry:
            continue
        yt_id = entry.get("id")
        if not yt_id:
            continue
        thumbnail_url = entry.get("thumbnail")
        if not thumbnail_url:
            thumbs = entry.get("thumbnails") or []
            if thumbs:
                thumbnail_url = thumbs[-1].get("url")
        results.append(
            {
                "youtube_video_id": yt_id,
                "title": entry.get("title", ""),
                "duration": entry.get("duration"),
                "url": entry.get("url") or f"https://www.youtube.com/watch?v={yt_id}",
                "thumbnail_url": thumbnail_url,
            }
        )
    return results


def _call_api(api_client: Any, candidates: list[str], *args: Any, **kwargs: Any) -> Any:
    for name in candidates:
        method = getattr(api_client, name, None)
        if callable(method):
            return method(*args, **kwargs)
    raise AttributeError(f"Missing API method; tried: {', '.join(candidates)}")


def sync_all_channels(api_client: Any, settings: Any) -> int:
    created_total = 0
    default_org_id = getattr(settings, "youtube_org_id", "") or getattr(api_client, "org_id", "")
    channels = _call_api(
        api_client,
        ["list_enabled_youtube_channels", "list_youtube_channels_for_sync", "list_youtube_channels"],
    )
    for channel in channels:
        channel_id = str(channel["id"])
        org_id = str(channel.get("org_id", default_org_id))
        channel_url = channel["channel_url"]
        try:
            cookies = getattr(settings, "youtube_cookies_path", "") or None
            discovered = enumerate_channel(channel_url, cookies_path=cookies)
            existing_ids = set(
                _call_api(
                    api_client,
                    ["list_youtube_video_ids", "list_existing_youtube_video_ids"],
                    channel_id=channel_id,
                    org_id=org_id,
                )
            )
            new_items = [item for item in discovered if item["youtube_video_id"] not in existing_ids]
            for item in new_items:
                payload = {
                    "org_id": org_id,
                    "channel_id": channel_id,
                    "youtube_video_id": item["youtube_video_id"],
                    "video_id": youtube_video_id(org_id, item["youtube_video_id"]),
                    "title": item["title"],
                    "duration_seconds": item["duration"],
                    "thumbnail_url": item["thumbnail_url"],
                    "video_url": item["url"],
                }
                _call_api(
                    api_client,
                    ["create_youtube_video", "upsert_youtube_video"],
                    payload,
                    org_id=org_id,
                )
            _call_api(
                api_client,
                ["mark_youtube_channel_synced", "update_youtube_channel_sync"],
                channel_id=channel_id,
                discovered_count=len(discovered),
                created_count=len(new_items),
                org_id=org_id,
            )
            created_total += len(new_items)
            logger.info(
                "youtube_channel_sync_complete",
                extra={
                    "channel_id": channel_id,
                    "discovered_count": len(discovered),
                    "created_count": len(new_items),
                },
            )
        except Exception:
            logger.exception("youtube_channel_sync_failed", extra={"channel_id": channel_id})
    return created_total
