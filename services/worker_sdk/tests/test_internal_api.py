"""
Tests for InternalAPIClient — HTTP client for internal drive API endpoints.

Covers:
- claim_jobs: success, empty, HTTP errors, audio_s3_key field
- update_job_status: success (caption/stt/ocr), with error, 404
- get_file: success, 404
- Retry behavior: transient errors with backoff, non-retryable errors
- Connection error handling
"""
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
import requests

from heimdex_worker_sdk.internal_api import InternalAPIClient, ClaimedFile


@pytest.fixture
def client():
    """Create an InternalAPIClient with fast retries for testing."""
    return InternalAPIClient(
        base_url="http://api:8000",
        api_key="test-key",
        max_retries=2,
        backoff_base=0.001,  # 1ms for fast tests
        backoff_max=0.01,
        timeout=5,
    )


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


# ── claim_jobs tests ──────────────────────────────────────────────────

class TestClaimJobs:
    def test_claim_returns_files(self, client):
        file_id = str(uuid4())
        org_id = str(uuid4())
        resp_data = {
            "files": [
                {
                    "id": file_id,
                    "org_id": org_id,
                    "video_id": "gd_abc123",
                    "keyframe_s3_prefix": "orgs/o/files/v/keyframes/",
                    "audio_s3_key": "orgs/o/files/v/audio.wav",
                }
            ]
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            files = client.claim_jobs("caption", limit=1)

        assert len(files) == 1
        assert isinstance(files[0], ClaimedFile)
        assert files[0].id == UUID(file_id)
        assert files[0].org_id == UUID(org_id)
        assert files[0].video_id == "gd_abc123"
        assert files[0].keyframe_s3_prefix == "orgs/o/files/v/keyframes/"
        assert files[0].audio_s3_key == "orgs/o/files/v/audio.wav"

    def test_claim_empty_returns_empty_list(self, client):
        with patch.object(client._session, "request", return_value=_mock_response(200, {"files": []})):
            files = client.claim_jobs("caption")

        assert files == []

    def test_claim_sends_correct_payload(self, client):
        with patch.object(client._session, "request", return_value=_mock_response(200, {"files": []})) as mock_req:
            client.claim_jobs("stt", limit=5)

        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args
        assert call_kwargs[0] == ("POST", "http://api:8000/internal/drive/jobs/claim")
        assert call_kwargs[1]["json"] == {"job_type": "stt", "limit": 5}

    def test_claim_no_keyframe_prefix(self, client):
        file_id = str(uuid4())
        org_id = str(uuid4())
        resp_data = {
            "files": [
                {
                    "id": file_id,
                    "org_id": org_id,
                    "video_id": "gd_xyz",
                }
            ]
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            files = client.claim_jobs("caption")

        assert files[0].keyframe_s3_prefix is None
        assert files[0].audio_s3_key is None


# ── update_job_status tests (generic — caption, stt, ocr) ────────────

class TestUpdateJobStatus:
    def test_update_caption_success(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})):
            result = client.update_job_status(file_id, job_type="caption", status="done")

        assert result is True

    def test_update_caption_with_error(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_job_status(
                file_id, job_type="caption", status="failed", error="model_crash"
            )

        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["json"] == {
            "job_type": "caption",
            "status": "failed",
            "error": "model_crash",
        }

    def test_update_stt_success(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})):
            result = client.update_job_status(file_id, job_type="stt", status="done")

        assert result is True

    def test_update_stt_with_error(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_job_status(
                file_id, job_type="stt", status="failed", error="whisper_oom"
            )

        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["json"] == {
            "job_type": "stt",
            "status": "failed",
            "error": "whisper_oom",
        }

    def test_update_ocr_success(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})):
            result = client.update_job_status(file_id, job_type="ocr", status="done")

        assert result is True

    def test_update_sends_correct_payload_without_error(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_job_status(file_id, job_type="stt", status="done")

        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["json"] == {
            "job_type": "stt",
            "status": "done",
        }

    def test_update_404_raises(self, client):
        file_id = uuid4()
        with patch.object(
            client._session, "request",
            return_value=_mock_response(404, text="Not found"),
        ):
            with pytest.raises(RuntimeError, match="404"):
                client.update_job_status(file_id, job_type="caption", status="done")

    def test_update_sends_correct_method_and_url(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_job_status(file_id, job_type="caption", status="done")

        call_args = mock_req.call_args[0]
        assert call_args[0] == "PATCH"
        assert f"/internal/drive/jobs/{file_id}/status" in call_args[1]


# ── get_file tests ────────────────────────────────────────────────────

class TestGetFile:
    def test_get_file_success(self, client):
        file_id = uuid4()
        resp_data = {
            "id": str(file_id),
            "org_id": str(uuid4()),
            "video_id": "gd_abc123",
            "keyframe_s3_prefix": "prefix/",
            "audio_s3_key": "audio/key.wav",
            "caption_status": "running",
            "stt_status": "done",
            "ocr_status": None,
            "enrichment_state": "running",
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            result = client.get_file(file_id)

        assert result["video_id"] == "gd_abc123"
        assert result["caption_status"] == "running"
        assert result["audio_s3_key"] == "audio/key.wav"

    def test_get_file_404_raises(self, client):
        with patch.object(
            client._session, "request",
            return_value=_mock_response(404, text="Not found"),
        ):
            with pytest.raises(RuntimeError, match="404"):
                client.get_file(uuid4())


# ── Retry behavior tests ─────────────────────────────────────────────

class TestRetryBehavior:
    def test_retries_on_502(self, client):
        """502 should trigger retry, then succeed on second attempt."""
        responses = [
            _mock_response(502, text="Bad Gateway"),
            _mock_response(200, {"files": []}),
        ]

        with patch.object(client._session, "request", side_effect=responses):
            files = client.claim_jobs("caption")

        assert files == []

    def test_retries_on_503(self, client):
        responses = [
            _mock_response(503, text="Service Unavailable"),
            _mock_response(200, {"ok": True}),
        ]

        with patch.object(client._session, "request", side_effect=responses):
            result = client.update_job_status(uuid4(), job_type="caption", status="done")

        assert result is True

    def test_retries_on_429(self, client):
        responses = [
            _mock_response(429, text="Too Many Requests"),
            _mock_response(200, {"files": []}),
        ]

        with patch.object(client._session, "request", side_effect=responses):
            files = client.claim_jobs("caption")

        assert files == []

    def test_does_not_retry_on_400(self, client):
        with patch.object(
            client._session, "request",
            return_value=_mock_response(400, text="Bad Request"),
        ):
            with pytest.raises(RuntimeError, match="400"):
                client.claim_jobs("caption")

    def test_does_not_retry_on_401(self, client):
        with patch.object(
            client._session, "request",
            return_value=_mock_response(401, text="Unauthorized"),
        ):
            with pytest.raises(RuntimeError, match="401"):
                client.claim_jobs("caption")

    def test_exhausts_retries_on_persistent_502(self, client):
        """All retries fail → raises RuntimeError."""
        responses = [
            _mock_response(502, text="Bad Gateway"),
            _mock_response(502, text="Bad Gateway"),
            _mock_response(502, text="Bad Gateway"),  # max_retries=2 → 3 attempts total
        ]

        with patch.object(client._session, "request", side_effect=responses):
            with pytest.raises(RuntimeError, match="502"):
                client.claim_jobs("caption")

    def test_retries_on_connection_error(self, client):
        responses = [
            requests.ConnectionError("Connection refused"),
            _mock_response(200, {"files": []}),
        ]

        with patch.object(client._session, "request", side_effect=responses):
            files = client.claim_jobs("caption")

        assert files == []

    def test_retries_on_timeout(self, client):
        responses = [
            requests.Timeout("Request timed out"),
            _mock_response(200, {"files": []}),
        ]

        with patch.object(client._session, "request", side_effect=responses):
            files = client.claim_jobs("caption")

        assert files == []

    def test_exhausts_retries_on_persistent_connection_error(self, client):
        errors = [
            requests.ConnectionError("fail"),
            requests.ConnectionError("fail"),
            requests.ConnectionError("fail"),
        ]

        with patch.object(client._session, "request", side_effect=errors):
            with pytest.raises(RuntimeError, match="failed after"):
                client.claim_jobs("caption")


# ── Auth header tests ─────────────────────────────────────────────────

class TestAuthHeaders:
    def test_session_has_auth_header(self, client):
        assert client._session.headers["Authorization"] == "Bearer test-key"
        assert client._session.headers["Content-Type"] == "application/json"


# ── Backoff calculation tests ─────────────────────────────────────────

class TestBackoff:
    def test_exponential_backoff(self, client):
        assert client._backoff_delay(0) == pytest.approx(0.001)
        assert client._backoff_delay(1) == pytest.approx(0.002)
        assert client._backoff_delay(2) == pytest.approx(0.004)

    def test_backoff_capped(self, client):
        # Even with high attempt number, should not exceed backoff_max
        assert client._backoff_delay(100) == pytest.approx(0.01)
