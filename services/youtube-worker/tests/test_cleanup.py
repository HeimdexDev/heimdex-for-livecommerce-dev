from unittest.mock import MagicMock, patch

from src.tasks.cleanup import cleanup_completed_videos


def test_cleanup_completed_videos_deleted(settings):
    api = MagicMock()
    api.list_youtube_cleanup_candidates.return_value = [
        {
            "id": "pk1",
            "org_id": "org-1",
            "channel_id": "UC123",
            "channel_external_id": "UC123",
            "youtube_video_id": "vid1",
            "video_id": "yt_1",
            "all_enrichment_complete": True,
            "original_deleted": False,
        }
    ]
    s3 = MagicMock()
    with patch("src.tasks.cleanup.S3Client", return_value=s3):
        deleted = cleanup_completed_videos(api, settings)

    assert deleted == 1
    api.mark_youtube_original_deleted.assert_called_once_with("pk1", original_deleted=True, org_id="org-1")
    assert s3.delete.call_count == 3


def test_cleanup_incomplete_videos_skipped(settings):
    api = MagicMock()
    api.list_youtube_cleanup_candidates.return_value = [
        {
            "id": "pk1",
            "org_id": "org-1",
            "channel_id": "UC123",
            "youtube_video_id": "vid1",
            "video_id": "yt_1",
            "all_enrichment_complete": False,
            "original_deleted": False,
        }
    ]
    with patch("src.tasks.cleanup.S3Client", return_value=MagicMock()):
        deleted = cleanup_completed_videos(api, settings)

    assert deleted == 0
    api.mark_youtube_original_deleted.assert_not_called()


def test_cleanup_handles_s3_error(settings):
    api = MagicMock()
    api.list_youtube_cleanup_candidates.return_value = [
        {
            "id": "pk1",
            "org_id": "org-1",
            "channel_id": "UC123",
            "youtube_video_id": "vid1",
            "video_id": "yt_1",
            "all_enrichment_complete": True,
            "original_deleted": False,
        }
    ]
    s3 = MagicMock()
    s3.delete.side_effect = RuntimeError("s3 error")

    with patch("src.tasks.cleanup.S3Client", return_value=s3):
        deleted = cleanup_completed_videos(api, settings)

    assert deleted == 0
    api.mark_youtube_original_deleted.assert_not_called()
