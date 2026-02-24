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

from heimdex_worker_sdk.internal_api import (
    AccessToken,
    ClaimedConnection,
    ClaimedFile,
    ClaimedProcessingFile,
    InternalAPIClient,
    UpsertResult,
)


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
        lease_token = str(uuid4())
        resp_data = {
            "files": [
                {
                    "id": file_id,
                    "org_id": org_id,
                    "video_id": "gd_abc123",
                    "keyframe_s3_prefix": "orgs/o/files/v/keyframes/",
                    "audio_s3_key": "orgs/o/files/v/audio.wav",
                    "lease_token": lease_token,
                    "lease_expires_at": "2026-02-24T10:30:00+00:00",
                }
            ]
        }
        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            files = client.claim_jobs("caption", limit=1)
        assert isinstance(files[0], ClaimedFile)
        assert files[0].id == UUID(file_id)
        assert files[0].org_id == UUID(org_id)
        assert files[0].video_id == "gd_abc123"
        assert files[0].keyframe_s3_prefix == "orgs/o/files/v/keyframes/"
        assert files[0].audio_s3_key == "orgs/o/files/v/audio.wav"
        assert files[0].lease_token == lease_token
        assert files[0].lease_expires_at == "2026-02-24T10:30:00+00:00"

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

    def test_claim_returns_lease_fields(self, client):
        file_id = str(uuid4())
        org_id = str(uuid4())
        token = str(uuid4())
        resp_data = {
            "files": [
                {
                    "id": file_id,
                    "org_id": org_id,
                    "video_id": "gd_lease",
                    "lease_token": token,
                    "lease_expires_at": "2026-02-24T11:00:00+00:00",
                }
            ]
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            files = client.claim_jobs("caption")

        assert files[0].lease_token == token
        assert files[0].lease_expires_at == "2026-02-24T11:00:00+00:00"

    def test_claim_no_lease_fields(self, client):
        resp_data = {
            "files": [
                {
                    "id": str(uuid4()),
                    "org_id": str(uuid4()),
                    "video_id": "gd_old",
                }
            ]
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            files = client.claim_jobs("caption")

        assert files[0].lease_token is None
        assert files[0].lease_expires_at is None


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

    def test_update_sends_lease_token(self, client):
        file_id = uuid4()
        token = str(uuid4())
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_job_status(
                file_id, job_type="caption", status="done", lease_token=token,
            )

        call_kwargs = mock_req.call_args
        assert call_kwargs[1]["json"] == {
            "job_type": "caption",
            "status": "done",
            "lease_token": token,
        }

    def test_update_omits_lease_token_when_none(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_job_status(file_id, job_type="caption", status="done")

        call_kwargs = mock_req.call_args
        assert "lease_token" not in call_kwargs[1]["json"]

    def test_update_sends_lease_token_with_error(self, client):
        file_id = uuid4()
        token = str(uuid4())
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_job_status(
                file_id, job_type="stt", status="failed",
                error="oom", lease_token=token,
            )

        call_kwargs = mock_req.call_args
        payload = call_kwargs[1]["json"]
        assert payload["lease_token"] == token
        assert payload["error"] == "oom"
        assert payload["job_type"] == "stt"
        assert payload["status"] == "failed"


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


class TestClaimConnection:
    def test_claim_connection_returns_connections(self, client):
        connection_id = str(uuid4())
        org_id = str(uuid4())
        library_id = str(uuid4())
        resp_data = {
            "connections": [
                {
                    "connection_id": connection_id,
                    "org_id": org_id,
                    "library_id": library_id,
                    "scope_type": "drive",
                    "drive_id": "drive-123",
                    "lease_token": str(uuid4()),
                    "lease_expires_at": "2026-02-24T10:30:00+00:00",
                }
            ]
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            result = client.claim_connection(limit=1)

        assert len(result) == 1
        assert isinstance(result[0], ClaimedConnection)
        assert result[0].connection_id == UUID(connection_id)
        assert result[0].org_id == UUID(org_id)
        assert result[0].library_id == UUID(library_id)
        assert result[0].scope_type == "drive"

    def test_claim_connection_empty_list(self, client):
        with patch.object(client._session, "request", return_value=_mock_response(200, {"connections": []})):
            result = client.claim_connection()

        assert result == []

    def test_claim_connection_sends_correct_payload(self, client):
        with patch.object(client._session, "request", return_value=_mock_response(200, {"connections": []})) as mock_req:
            client.claim_connection(limit=3)

        call_args = mock_req.call_args
        assert call_args[0] == ("POST", "http://api:8000/internal/drive/sync/claim_connection")
        assert call_args[1]["json"] == {"limit": 3}


class TestUpsertFiles:
    def test_upsert_files_success(self, client):
        connection_id = uuid4()
        resp_data = {
            "created_count": 2,
            "updated_count": 0,
            "unchanged_count": 1,
            "enqueued_jobs": {"processing": 2},
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            result = client.upsert_files(
                connection_id,
                lease_token="lease-123",
                items=[{"provider_file_id": "abc"}],
            )

        assert isinstance(result, UpsertResult)
        assert result.created_count == 2
        assert result.updated_count == 0
        assert result.unchanged_count == 1
        assert result.enqueued_jobs == {"processing": 2}

    def test_upsert_files_sends_correct_payload_and_url(self, client):
        connection_id = uuid4()
        items = [{"provider_file_id": "x", "name": "a.mp4"}]
        with patch.object(client._session, "request", return_value=_mock_response(200, {
            "created_count": 0,
            "updated_count": 0,
            "unchanged_count": 1,
            "enqueued_jobs": {},
        })) as mock_req:
            client.upsert_files(connection_id, lease_token="lease-xyz", items=items)

        call_args = mock_req.call_args
        assert call_args[0] == (
            "POST",
            f"http://api:8000/internal/drive/sync/connections/{connection_id}/upsert_files",
        )
        assert call_args[1]["json"] == {"lease_token": "lease-xyz", "items": items}


class TestCheckpoint:
    def test_checkpoint_success_defaults_release_true(self, client):
        connection_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})):
            result = client.checkpoint(connection_id, lease_token="lease-123")

        assert result is True

    def test_checkpoint_release_false(self, client):
        connection_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.checkpoint(connection_id, lease_token="lease-123", release=False)

        assert mock_req.call_args[1]["json"] == {"lease_token": "lease-123", "release": False}

    def test_checkpoint_with_optional_fields(self, client):
        connection_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.checkpoint(
                connection_id,
                lease_token="lease-123",
                change_token="token-next",
                last_sync_at="2026-02-24T10:00:00+00:00",
                last_full_sync_at="2026-02-24T09:00:00+00:00",
                error_message="rate limited",
            )

        assert mock_req.call_args[1]["json"] == {
            "lease_token": "lease-123",
            "release": True,
            "change_token": "token-next",
            "last_sync_at": "2026-02-24T10:00:00+00:00",
            "last_full_sync_at": "2026-02-24T09:00:00+00:00",
            "error_message": "rate limited",
        }


class TestGetDriveToken:
    def test_get_drive_token_success(self, client):
        connection_id = uuid4()
        resp_data = {
            "access_token": "ya29.token",
            "token_type": "Bearer",
            "expires_at": "2026-02-24T12:00:00+00:00",
            "scope_type": "drive",
        }
        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            token = client.get_drive_token(connection_id, lease_token="lease-abc")

        assert isinstance(token, AccessToken)
        assert token.access_token == "ya29.token"
        assert token.token_type == "Bearer"
        assert token.scope_type == "drive"

    def test_get_drive_token_sends_correct_payload(self, client):
        connection_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {
            "access_token": "t",
            "token_type": "Bearer",
            "expires_at": "2026-02-24T12:00:00+00:00",
            "scope_type": "folder",
        })) as mock_req:
            client.get_drive_token(connection_id, lease_token="lease-xyz")

        assert mock_req.call_args[0] == (
            "POST",
            f"http://api:8000/internal/drive/sync/connections/{connection_id}/token",
        )
        assert mock_req.call_args[1]["json"] == {"lease_token": "lease-xyz"}


class TestClaimProcessing:
    def test_claim_processing_returns_files(self, client):
        file_id = str(uuid4())
        org_id = str(uuid4())
        connection_id = str(uuid4())
        library_id = str(uuid4())
        resp_data = {
            "files": [
                {
                    "id": file_id,
                    "org_id": org_id,
                    "connection_id": connection_id,
                    "google_file_id": "google-1",
                    "file_name": "video.mp4",
                    "video_id": "gd_abc",
                    "mime_type": "video/mp4",
                    "md5_checksum": "deadbeef",
                    "file_size_bytes": 123,
                    "drive_path": "Folder/video.mp4",
                    "library_id": library_id,
                    "scope_type": "drive",
                    "drive_id": "drive-1",
                    "lease_token": str(uuid4()),
                    "lease_expires_at": "2026-02-24T10:30:00+00:00",
                }
            ]
        }

        with patch.object(client._session, "request", return_value=_mock_response(200, resp_data)):
            files = client.claim_processing(limit=1)

        assert len(files) == 1
        assert isinstance(files[0], ClaimedProcessingFile)
        assert files[0].id == UUID(file_id)
        assert files[0].org_id == UUID(org_id)
        assert files[0].connection_id == UUID(connection_id)
        assert files[0].library_id == UUID(library_id)

    def test_claim_processing_empty_list(self, client):
        with patch.object(client._session, "request", return_value=_mock_response(200, {"files": []})):
            files = client.claim_processing()

        assert files == []

    def test_claim_processing_sends_correct_payload(self, client):
        with patch.object(client._session, "request", return_value=_mock_response(200, {"files": []})) as mock_req:
            client.claim_processing(limit=2)

        assert mock_req.call_args[0] == ("POST", "http://api:8000/internal/drive/processing/claim")
        assert mock_req.call_args[1]["json"] == {"limit": 2}


class TestUpdateProcessingStatus:
    def test_update_processing_status_success(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})):
            result = client.update_processing_status(file_id, status="transcoding")

        assert result is True

    def test_update_processing_status_with_error(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_processing_status(
                file_id,
                status="failed",
                lease_token="lease-123",
                error="download failed",
            )

        assert mock_req.call_args[1]["json"] == {
            "status": "failed",
            "lease_token": "lease-123",
            "error": "download failed",
        }

    def test_update_processing_status_with_optional_metadata(self, client):
        file_id = uuid4()
        with patch.object(client._session, "request", return_value=_mock_response(200, {"ok": True})) as mock_req:
            client.update_processing_status(
                file_id,
                status="indexed",
                proxy_s3_key="proxy/key.mp4",
                proxy_size_bytes=100,
                proxy_duration_ms=200,
                thumbnail_s3_prefix="thumbs/",
                scene_count=3,
                audio_s3_key="audio/key.wav",
                keyframe_s3_prefix="keyframes/",
            )

        assert mock_req.call_args[1]["json"] == {
            "status": "indexed",
            "proxy_s3_key": "proxy/key.mp4",
            "proxy_size_bytes": 100,
            "proxy_duration_ms": 200,
            "thumbnail_s3_prefix": "thumbs/",
            "scene_count": 3,
            "audio_s3_key": "audio/key.wav",
            "keyframe_s3_prefix": "keyframes/",
        }

    def test_update_processing_status_404_raises(self, client):
        with patch.object(
            client._session,
            "request",
            return_value=_mock_response(404, text="Not found"),
        ):
            with pytest.raises(RuntimeError, match="404"):
                client.update_processing_status(uuid4(), status="indexed")


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
