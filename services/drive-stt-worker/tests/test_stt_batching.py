"""Tests for STT worker enrichment batching and YouTube job status skipping."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src directory to path for imports
src_dir = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_dir))

from tasks.stt import _safe_update_job_status, _post_enrich_to_api


def _make_settings(api_base="http://api:8000", api_key="test-key"):
    """Create a mock settings object."""
    s = MagicMock()
    s.drive_api_base_url = api_base
    s.drive_internal_api_key = api_key
    return s


class TestSafeUpdateJobStatus:
    """Tests for _safe_update_job_status function."""

    def test_skips_youtube_video_ids(self):
        """YouTube video IDs (yt_ prefix) should NOT call update_job_status."""
        api_client = MagicMock()
        _safe_update_job_status(
            api_client, "yt_abc123", "file-uuid", job_type="stt", status="done"
        )
        api_client.update_job_status.assert_not_called()

    def test_calls_for_gdrive_video_ids(self):
        """Google Drive video IDs (gd_ prefix) SHOULD call update_job_status."""
        api_client = MagicMock()
        _safe_update_job_status(
            api_client,
            "gd_abc123",
            "file-uuid",
            job_type="stt",
            status="done",
            lease_token="tok",
        )
        api_client.update_job_status.assert_called_once_with(
            "file-uuid", job_type="stt", status="done", lease_token="tok"
        )

    def test_calls_for_regular_video_ids(self):
        """Non-prefixed video IDs should also call update_job_status."""
        api_client = MagicMock()
        _safe_update_job_status(
            api_client, "some_other_id", "file-uuid", job_type="stt", status="failed"
        )
        api_client.update_job_status.assert_called_once_with(
            "file-uuid", job_type="stt", status="failed"
        )

    def test_passes_all_kwargs(self):
        """All kwargs should be passed through to update_job_status."""
        api_client = MagicMock()
        _safe_update_job_status(
            api_client,
            "gd_vid123",
            "file-id",
            job_type="stt",
            status="done",
            lease_token="token123",
            error="some_error",
        )
        api_client.update_job_status.assert_called_once_with(
            "file-id",
            job_type="stt",
            status="done",
            lease_token="token123",
            error="some_error",
        )


class TestPostEnrichToApi:
    """Tests for _post_enrich_to_api function."""

    def test_batches_at_200_scenes(self):
        """450 scenes should result in 3 API calls (200 + 200 + 50)."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated_count": 200}
        mock_requests.post.return_value = mock_response

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "requests":
                return mock_requests
            return original_import(name, *args, **kwargs)

        # Build 450 scenes with STT fields
        scenes = [
            {
                "scene_id": f"scene_{i}",
                "transcript_raw": f"transcript {i}",
                "speech_segment_count": 2,
            }
            for i in range(450)
        ]

        with patch("importlib.import_module", side_effect=patched_import):
            result = _post_enrich_to_api(
                settings=_make_settings(),
                org_id="org-1",
                video_id="vid-1",
                scenes=scenes,
            )

        assert mock_requests.post.call_count == 3
        assert result["updated_count"] == 600  # 3 * 200
        assert result["video_id"] == "vid-1"

    def test_single_batch_under_200(self):
        """150 scenes should result in 1 API call."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated_count": 150}
        mock_requests.post.return_value = mock_response

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "requests":
                return mock_requests
            return original_import(name, *args, **kwargs)

        scenes = [
            {
                "scene_id": f"scene_{i}",
                "transcript_raw": f"transcript {i}",
                "speech_segment_count": 1,
            }
            for i in range(150)
        ]

        with patch("importlib.import_module", side_effect=patched_import):
            result = _post_enrich_to_api(
                settings=_make_settings(),
                org_id="org-1",
                video_id="vid-1",
                scenes=scenes,
            )

        assert mock_requests.post.call_count == 1
        assert result["updated_count"] == 150

    def test_exact_boundary_200(self):
        """200 scenes should result in 1 API call (not 2)."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated_count": 200}
        mock_requests.post.return_value = mock_response

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "requests":
                return mock_requests
            return original_import(name, *args, **kwargs)

        scenes = [
            {
                "scene_id": f"scene_{i}",
                "transcript_raw": f"transcript {i}",
                "speech_segment_count": 0,
            }
            for i in range(200)
        ]

        with patch("importlib.import_module", side_effect=patched_import):
            result = _post_enrich_to_api(
                settings=_make_settings(),
                org_id="org-1",
                video_id="vid-1",
                scenes=scenes,
            )

        assert mock_requests.post.call_count == 1
        assert result["updated_count"] == 200

    def test_empty_scenes(self):
        """Empty scenes list should return early without API calls."""
        mock_requests = MagicMock()

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "requests":
                return mock_requests
            return original_import(name, *args, **kwargs)

        with patch("importlib.import_module", side_effect=patched_import):
            result = _post_enrich_to_api(
                settings=_make_settings(),
                org_id="org-1",
                video_id="vid-1",
                scenes=[],
            )

        # STT always includes all scenes, so empty list should still call API
        # (with empty enrich_scenes list)
        assert mock_requests.post.call_count == 0
        assert result["updated_count"] == 0

    def test_api_error_raises(self):
        """Non-200 response should raise RuntimeError."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_requests.post.return_value = mock_response

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "requests":
                return mock_requests
            return original_import(name, *args, **kwargs)

        scenes = [
            {
                "scene_id": "scene_1",
                "transcript_raw": "test",
                "speech_segment_count": 1,
            }
        ]

        with patch("importlib.import_module", side_effect=patched_import):
            try:
                _post_enrich_to_api(
                    settings=_make_settings(),
                    org_id="org-1",
                    video_id="vid-1",
                    scenes=scenes,
                )
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "500" in str(e)
                assert "Internal Server Error" in str(e)

    def test_includes_speaker_transcript_when_present(self):
        """Scenes with speaker_transcript should include those fields."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated_count": 1}
        mock_requests.post.return_value = mock_response

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "requests":
                return mock_requests
            return original_import(name, *args, **kwargs)

        scenes = [
            {
                "scene_id": "scene_1",
                "transcript_raw": "test transcript",
                "speech_segment_count": 2,
                "speaker_transcript": "Speaker 1: hello\nSpeaker 2: world",
                "speaker_count": 2,
            }
        ]

        with patch("importlib.import_module", side_effect=patched_import):
            _post_enrich_to_api(
                settings=_make_settings(),
                org_id="org-1",
                video_id="vid-1",
                scenes=scenes,
            )

        # Verify the payload includes speaker fields
        call_args = mock_requests.post.call_args
        payload = call_args.kwargs["json"]
        assert len(payload["scenes"]) == 1
        assert payload["scenes"][0]["speaker_transcript"] == "Speaker 1: hello\nSpeaker 2: world"
        assert payload["scenes"][0]["speaker_count"] == 2

    def test_correct_headers(self):
        """API call should include correct headers."""
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"updated_count": 1}
        mock_requests.post.return_value = mock_response

        original_import = __import__

        def patched_import(name, *args, **kwargs):
            if name == "requests":
                return mock_requests
            return original_import(name, *args, **kwargs)

        scenes = [
            {
                "scene_id": "scene_1",
                "transcript_raw": "test",
                "speech_segment_count": 0,
            }
        ]

        settings = _make_settings(api_base="http://api:8000", api_key="secret-key")

        with patch("importlib.import_module", side_effect=patched_import):
            _post_enrich_to_api(
                settings=settings,
                org_id="org-123",
                video_id="vid-1",
                scenes=scenes,
            )

        call_args = mock_requests.post.call_args
        assert call_args.args[0] == "http://api:8000/internal/ingest/enrich"
        headers = call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret-key"
        assert headers["X-Heimdex-Org-Id"] == "org-123"
        assert headers["Content-Type"] == "application/json"
