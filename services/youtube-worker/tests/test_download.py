from pathlib import Path
from unittest.mock import MagicMock, patch

from src.tasks.download import download_and_upload_video


def _make_downloader(temp_dir: Path, with_subs: bool = True):
    class _Downloader:
        def extract_info(self, *_args, **_kwargs):
            (temp_dir / "dQw4w9WgXcQ.mp4").write_bytes(b"video")
            (temp_dir / "dQw4w9WgXcQ.info.json").write_text('{"id":"dQw4w9WgXcQ"}')
            if with_subs:
                (temp_dir / "dQw4w9WgXcQ.ko.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n안녕하세요")

    return _Downloader()


def test_download_success_with_subtitles(settings, video_record):
    temp_dir = Path(settings.youtube_temp_dir) / "org-1" / "dQw4w9WgXcQ"
    api = MagicMock()
    s3 = MagicMock()

    with patch("yt_dlp.YoutubeDL", return_value=_make_downloader(temp_dir, with_subs=True)):
        with patch("src.tasks.download.S3Client", return_value=s3):
            with patch("src.tasks.download.time.sleep"):
                ok = download_and_upload_video(api, settings, video_record)

    assert ok is True
    assert s3.upload_file.call_count == 3
    api.publish_youtube_transcode_job.assert_called_once()
    assert not temp_dir.exists()


def test_download_success_without_subtitles(settings, video_record):
    temp_dir = Path(settings.youtube_temp_dir) / "org-1" / "dQw4w9WgXcQ"
    api = MagicMock()
    s3 = MagicMock()

    with patch("yt_dlp.YoutubeDL", return_value=_make_downloader(temp_dir, with_subs=False)):
        with patch("src.tasks.download.S3Client", return_value=s3):
            with patch("src.tasks.download.time.sleep"):
                ok = download_and_upload_video(api, settings, video_record)

    assert ok is True
    assert s3.upload_file.call_count == 2
    assert not temp_dir.exists()


def test_download_failure_marks_failed(settings, video_record):
    api = MagicMock()
    ydl = MagicMock()
    ydl.extract_info.side_effect = RuntimeError("download failed")

    with patch("yt_dlp.YoutubeDL", return_value=ydl):
        with patch("src.tasks.download.S3Client"):
            with patch("src.tasks.download.time.sleep"):
                ok = download_and_upload_video(api, settings, video_record)

    assert ok is False
    assert any(call.kwargs.get("status") == "failed" for call in api.update_youtube_video_status.call_args_list)


def test_s3_upload_failure_marks_failed_and_cleans_temp(settings, video_record):
    temp_dir = Path(settings.youtube_temp_dir) / "org-1" / "dQw4w9WgXcQ"
    api = MagicMock()
    s3 = MagicMock()
    s3.upload_file.side_effect = RuntimeError("s3 down")

    with patch("yt_dlp.YoutubeDL", return_value=_make_downloader(temp_dir, with_subs=True)):
        with patch("src.tasks.download.S3Client", return_value=s3):
            with patch("src.tasks.download.time.sleep"):
                ok = download_and_upload_video(api, settings, video_record)

    assert ok is False
    assert any(call.kwargs.get("status") == "failed" for call in api.update_youtube_video_status.call_args_list)
    assert not temp_dir.exists()


def test_download_with_mocked_boto3_client(settings, video_record):
    temp_dir = Path(settings.youtube_temp_dir) / "org-1" / "dQw4w9WgXcQ"
    api = MagicMock()

    import heimdex_worker_sdk.s3 as s3_module

    s3_module._build_s3_client.cache_clear()
    boto3_client = MagicMock()
    boto3_client.exceptions.ClientError = Exception

    worker_settings = MagicMock()
    worker_settings.minio_endpoint = "disabled"
    worker_settings.s3_region = "ap-northeast-2"
    worker_settings.drive_s3_bucket = settings.drive_s3_bucket

    with patch("yt_dlp.YoutubeDL", return_value=_make_downloader(temp_dir, with_subs=True)):
        with patch("heimdex_worker_sdk.s3.get_worker_settings", return_value=worker_settings):
            with patch("heimdex_worker_sdk.s3.boto3.client", return_value=boto3_client):
                with patch("src.tasks.download.time.sleep"):
                    ok = download_and_upload_video(api, settings, video_record)

    assert ok is True
    assert boto3_client.upload_file.call_count == 3
