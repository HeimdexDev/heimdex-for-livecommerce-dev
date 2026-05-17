from unittest.mock import MagicMock, patch

from src.tasks.enumerate import enumerate_channel, sync_all_channels


def test_enumerate_channel_listing_appends_videos_tab():
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {
        "entries": [
            {
                "id": "vid1",
                "title": "Video 1",
                "duration": 120,
                "thumbnail": "https://img/1.jpg",
            }
        ]
    }
    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl) as mock_ctor:
        results = enumerate_channel("https://www.youtube.com/@heimdex")

    assert len(results) == 1
    assert results[0]["youtube_video_id"] == "vid1"
    assert results[0]["url"] == "https://www.youtube.com/watch?v=vid1"
    mock_ydl.extract_info.assert_called_once_with("https://www.youtube.com/@heimdex/videos", download=False)
    assert mock_ctor.called


def test_enumerate_channel_empty_channel():
    mock_ydl = MagicMock()
    mock_ydl.extract_info.return_value = {"entries": []}
    with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
        assert enumerate_channel("https://www.youtube.com/@heimdex") == []


def test_sync_all_channels_filters_known_ids():
    api = MagicMock()
    api.list_enabled_youtube_channels.return_value = [
        {"org_id": "org-1", "channel_id": "UC123", "channel_url": "https://www.youtube.com/@heimdex"}
    ]
    api.list_youtube_video_ids.return_value = {"vid1"}

    with patch("src.tasks.enumerate.enumerate_channel", return_value=[
        {"youtube_video_id": "vid1", "title": "Old", "duration": 10, "thumbnail_url": "t1", "url": "u1"},
        {"youtube_video_id": "vid2", "title": "New", "duration": 20, "thumbnail_url": "t2", "url": "u2"},
    ]):
        created = sync_all_channels(api, settings=object())

    assert created == 1
    api.create_youtube_video.assert_called_once()
    payload = api.create_youtube_video.call_args[0][0]
    assert payload["youtube_video_id"] == "vid2"
    api.mark_youtube_channel_synced.assert_called_once()


def test_sync_all_channels_handles_enumeration_error():
    api = MagicMock()
    api.list_enabled_youtube_channels.return_value = [
        {"org_id": "org-1", "channel_id": "UC123", "channel_url": "https://www.youtube.com/@heimdex"}
    ]

    with patch("src.tasks.enumerate.enumerate_channel", side_effect=RuntimeError("boom")):
        created = sync_all_channels(api, settings=object())

    assert created == 0
    api.create_youtube_video.assert_not_called()
