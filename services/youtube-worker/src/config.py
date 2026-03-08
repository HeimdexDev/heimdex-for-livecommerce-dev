from functools import lru_cache
import importlib


WorkerSettings = importlib.import_module("heimdex_worker_sdk.settings").WorkerSettings


class YouTubeWorkerSettings(WorkerSettings):
    youtube_enabled: bool = False
    youtube_sync_interval_seconds: int = 21600
    youtube_download_format: str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
    youtube_rate_limit_sleep: int = 3
    youtube_rate_limit_max_sleep: int = 8
    youtube_max_concurrent_downloads: int = 2
    youtube_auto_delete_originals: bool = True
    youtube_original_ttl_days: int = 7
    youtube_temp_dir: str = "/data/youtube-tmp"


@lru_cache(maxsize=1)
def get_settings() -> YouTubeWorkerSettings:
    return YouTubeWorkerSettings()
