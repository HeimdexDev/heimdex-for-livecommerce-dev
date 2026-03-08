from unittest.mock import MagicMock, patch

import pytest
import requests

from heimdex_worker_sdk.youtube_api import YouTubeAPIClient


@pytest.fixture
def client():
    return YouTubeAPIClient(
        base_url="http://api:8000",
        api_key="test-key",
        org_id="11111111-1111-1111-1111-111111111111",
        max_retries=2,
        backoff_base=0.001,
        backoff_max=0.01,
        timeout=5,
    )


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def test_list_enabled_channels(client):
    with patch.object(client._session, "request", return_value=_mock_response(200, {"channels": [{"id": 1}]})) as mock_req:
        channels = client.list_enabled_youtube_channels()

    assert channels == [{"id": 1}]
    assert mock_req.call_args[0] == ("GET", "http://api:8000/internal/youtube/channels")


def test_list_video_ids_with_org_override(client):
    with patch.object(client._session, "request", return_value=_mock_response(200, {"video_ids": ["a", "b"]})) as mock_req:
        ids_ = client.list_youtube_video_ids(channel_id="channel-1", org_id="22222222-2222-2222-2222-222222222222")

    assert ids_ == ["a", "b"]
    headers = mock_req.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["X-Heimdex-Org-Id"] == "22222222-2222-2222-2222-222222222222"


def test_create_youtube_video(client):
    payload = {
        "org_id": "o1",
        "channel_id": "c1",
        "youtube_video_id": "yt1",
        "title": "Video",
        "duration_seconds": 12,
        "thumbnail_url": "https://img",
        "description": "desc",
        "video_url": "https://youtube.com/watch?v=yt1",
    }
    with patch.object(client._session, "request", return_value=_mock_response(201, {"id": "v1"})) as mock_req:
        out = client.create_youtube_video(payload)

    assert out == {"id": "v1"}
    assert mock_req.call_args[0] == ("POST", "http://api:8000/internal/youtube/channels/c1/videos")
    assert mock_req.call_args[1]["json"] == {
        "youtube_video_id": "yt1",
        "title": "Video",
        "duration_seconds": 12,
        "thumbnail_url": "https://img",
        "description": "desc",
    }


def test_mark_channel_synced(client):
    with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
        ok = client.mark_youtube_channel_synced(channel_id="c1", discovered_count=10, created_count=3)

    assert ok is True
    assert mock_req.call_args[0] == ("PATCH", "http://api:8000/internal/youtube/channels/c1/sync-complete")
    assert mock_req.call_args[1]["json"] == {"discovered_count": 10, "created_count": 3}


def test_update_video_status(client):
    with patch.object(client._session, "request", return_value=_mock_response(200, {"id": "v1"})) as mock_req:
        out = client.update_youtube_video_status("v1", status="failed", error="boom")

    assert out == {"id": "v1"}
    assert mock_req.call_args[0] == ("PATCH", "http://api:8000/internal/youtube/videos/v1/status")
    assert mock_req.call_args[1]["json"] == {"processing_status": "failed", "error": "boom"}


def test_publish_transcode_job(client):
    with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True, "message_sent": True})) as mock_req:
        sent = client.publish_youtube_transcode_job({"video_id": "vid"})

    assert sent is True
    assert mock_req.call_args[0] == ("POST", "http://api:8000/internal/youtube/transcode")


def test_claim_pending_downloads(client):
    with patch.object(client._session, "request", return_value=_mock_response(200, {"videos": [{"id": "v1"}]})) as mock_req:
        videos = client.claim_pending_youtube_downloads(limit=7)

    assert videos == [{"id": "v1"}]
    assert mock_req.call_args[0] == ("GET", "http://api:8000/internal/youtube/videos/pending")
    assert mock_req.call_args[1]["params"] == {"limit": 7}


def test_cleanup_candidates_and_mark_deleted(client):
    with patch.object(client._session, "request", side_effect=[
        _mock_response(200, {"videos": [{"id": "v1", "all_enrichment_complete": True}]}),
        _mock_response(200, {"id": "v1"}),
    ]):
        videos = client.list_youtube_cleanup_candidates()
        out = client.mark_youtube_original_deleted("v1", original_deleted=True)

    assert videos[0]["all_enrichment_complete"] is True
    assert out == {"id": "v1"}


def test_retry_on_503(client):
    responses = [
        _mock_response(503, text="busy"),
        _mock_response(200, {"videos": []}),
    ]
    with patch.object(client._session, "request", side_effect=responses):
        videos = client.list_youtube_cleanup_candidates()

    assert videos == []


def test_400_raises_runtime_error(client):
    with patch.object(client._session, "request", return_value=_mock_response(400, text="bad")):
        with pytest.raises(RuntimeError, match="400"):
            client.list_enabled_youtube_channels()


def test_retries_on_connection_error(client):
    responses = [requests.ConnectionError("no route"), _mock_response(200, {"channels": []})]
    with patch.object(client._session, "request", side_effect=responses):
        channels = client.list_enabled_youtube_channels()

    assert channels == []
