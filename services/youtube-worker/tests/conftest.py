from pathlib import Path
import sys
import types

import pytest


if "yt_dlp" not in sys.modules:
    yt_dlp_stub = types.ModuleType("yt_dlp")

    class _StubYoutubeDL:
        def __init__(self, *args, **kwargs):
            pass

        def extract_info(self, *args, **kwargs):
            return {}

    setattr(yt_dlp_stub, "YoutubeDL", _StubYoutubeDL)
    sys.modules["yt_dlp"] = yt_dlp_stub


@pytest.fixture
def settings(tmp_path: Path):
    class _Settings:
        youtube_download_format = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
        youtube_rate_limit_sleep = 0
        youtube_rate_limit_max_sleep = 0
        youtube_max_concurrent_downloads = 2
        youtube_original_ttl_days = 7
        youtube_temp_dir = str(tmp_path / "youtube-tmp")
        youtube_auto_delete_originals = True
        drive_s3_bucket = "heimdex-drive"

    return _Settings()


@pytest.fixture
def video_record():
    return {
        "id": "video-pk-1",
        "org_id": "org-1",
        "channel_id": "UC123",
        "channel_external_id": "UC123",
        "youtube_video_id": "dQw4w9WgXcQ",
        "video_id": "yt_abc123",
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }
