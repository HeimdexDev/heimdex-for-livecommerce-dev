"""Tests for SQS dual-write producer (Phase 1)."""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.sqs_producer import (
    _publish,
    publish_enrichment_jobs,
    publish_processing_job,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Build a mock Settings object with SQS fields."""
    defaults = {
        "sqs_enabled": False,
        "sqs_endpoint_url": "",
        "sqs_region": "ap-northeast-2",
        "sqs_processing_queue_url": "http://localhost:9324/000000000000/heimdex-processing-queue",
        "sqs_caption_queue_url": "http://localhost:9324/000000000000/heimdex-caption-queue",
        "sqs_stt_queue_url": "http://localhost:9324/000000000000/heimdex-stt-queue",
        "sqs_ocr_queue_url": "http://localhost:9324/000000000000/heimdex-ocr-queue",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


# ── SQS disabled (no-op) ─────────────────────────────────────────────────────


class TestSQSDisabled:
    """When sqs_enabled=False, no SQS calls should ever happen."""

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_publish_is_noop_when_disabled(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=False)
        _publish("processing", {"file_id": "abc"})
        mock_get_client.assert_not_called()

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_processing_noop_when_disabled(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=False)
        publish_processing_job(
            file_id=uuid4(),
            org_id=uuid4(),
            connection_id=uuid4(),
            video_id="gd_test123",
            google_file_id="gfile_abc",
            file_name="test.mp4",
            mime_type="video/mp4",
            file_size_bytes=1024,
            library_id=uuid4(),
            scope_type="drive",
            drive_id="0AO_drive",
        )
        mock_get_client.assert_not_called()

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_enrichment_noop_when_disabled(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=False)
        publish_enrichment_jobs(
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_test123",
            keyframe_s3_prefix="s3://prefix/",
            audio_s3_key="s3://audio.wav",
        )
        mock_get_client.assert_not_called()


# ── SQS enabled: correct messages ────────────────────────────────────────────


class TestSQSEnabled:
    """When sqs_enabled=True, verify correct SQS send_message calls."""

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_processing_job_published(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-001"}
        mock_get_client.return_value = mock_client

        file_id = uuid4()
        org_id = uuid4()
        publish_processing_job(
            file_id=file_id,
            org_id=org_id,
            connection_id=uuid4(),
            video_id="gd_test123",
            google_file_id="gfile_abc",
            file_name="test.mp4",
            mime_type="video/mp4",
            file_size_bytes=1024,
            library_id=uuid4(),
            scope_type="drive",
            drive_id="0AO_drive",
        )

        mock_client.send_message.assert_called_once()
        call_kwargs = mock_client.send_message.call_args[1]
        body = json.loads(call_kwargs["MessageBody"])
        assert body["version"] == "1"
        assert body["type"] == "processing.job_created"
        assert body["file_id"] == str(file_id)
        assert body["org_id"] == str(org_id)
        assert body["video_id"] == "gd_test123"
        assert body["file_name"] == "test.mp4"
        assert body["mime_type"] == "video/mp4"
        assert body["file_size_bytes"] == 1024
        assert "timestamp" in body
        # MessageAttributes
        attrs = call_kwargs["MessageAttributes"]
        assert attrs["job_type"]["StringValue"] == "processing"
        assert attrs["source"]["StringValue"] == "api"
        # Standard queues: no MessageDeduplicationId
        assert "MessageDeduplicationId" not in call_kwargs

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_processing_job_dedup_id_on_fifo_queue(self, mock_settings, mock_get_client):
        """FIFO queues should include MessageDeduplicationId."""
        mock_settings.return_value = _make_settings(
            sqs_enabled=True,
            sqs_processing_queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/heimdex-processing-queue.fifo",
        )
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-fifo-001"}
        mock_get_client.return_value = mock_client

        file_id = uuid4()
        publish_processing_job(
            file_id=file_id,
            org_id=uuid4(),
            connection_id=uuid4(),
            video_id="gd_test123",
            google_file_id="gfile_abc",
            file_name="test.mp4",
            mime_type="video/mp4",
            file_size_bytes=1024,
            library_id=uuid4(),
            scope_type="drive",
            drive_id="0AO_drive",
        )

        call_kwargs = mock_client.send_message.call_args[1]
        assert "MessageDeduplicationId" in call_kwargs
        assert call_kwargs["MessageDeduplicationId"].startswith(str(file_id))

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_enrichment_caption_and_ocr_on_keyframe(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-002"}
        mock_get_client.return_value = mock_client

        file_id = uuid4()
        publish_enrichment_jobs(
            file_id=file_id,
            org_id=uuid4(),
            video_id="gd_test123",
            keyframe_s3_prefix="drive/org/video/keyframes/",
            audio_s3_key=None,
        )

        # Caption + OCR + Face + Visual Embed = 4 calls
        assert mock_client.send_message.call_count == 4
        calls = mock_client.send_message.call_args_list
        job_types_sent = []
        for call in calls:
            body = json.loads(call[1]["MessageBody"])
            assert body["version"] == "1"
            assert body["type"] == "enrichment.job_created"
            assert body["keyframe_s3_prefix"] == "drive/org/video/keyframes/"
            assert body["audio_s3_key"] is None
            job_types_sent.append(body["job_type"])
        assert set(job_types_sent) == {"caption", "ocr", "face", "visual_embed"}

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_enrichment_stt_on_audio(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-003"}
        mock_get_client.return_value = mock_client

        publish_enrichment_jobs(
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_test123",
            keyframe_s3_prefix=None,
            audio_s3_key="drive/org/video/audio.wav",
        )

        # STT only = 1 call
        mock_client.send_message.assert_called_once()
        body = json.loads(mock_client.send_message.call_args[1]["MessageBody"])
        assert body["job_type"] == "stt"
        assert body["audio_s3_key"] == "drive/org/video/audio.wav"
        assert body["keyframe_s3_prefix"] is None

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_enrichment_all_three_when_both_artifacts(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-004"}
        mock_get_client.return_value = mock_client

        publish_enrichment_jobs(
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_test123",
            keyframe_s3_prefix="drive/org/video/keyframes/",
            audio_s3_key="drive/org/video/audio.wav",
        )

        # Caption + OCR + Face + Visual Embed + STT = 5 calls
        assert mock_client.send_message.call_count == 5

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_enrichment_no_messages_without_artifacts(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        publish_enrichment_jobs(
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_test123",
            keyframe_s3_prefix=None,
            audio_s3_key=None,
        )

        mock_client.send_message.assert_not_called()

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_correct_queue_urls_used(self, mock_settings, mock_get_client):
        settings = _make_settings(sqs_enabled=True)
        mock_settings.return_value = settings
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-005"}
        mock_get_client.return_value = mock_client

        # Processing job should use sqs_processing_queue_url
        publish_processing_job(
            file_id=uuid4(),
            org_id=uuid4(),
            connection_id=uuid4(),
            video_id="gd_test123",
            google_file_id="gfile_abc",
            file_name="test.mp4",
            mime_type="video/mp4",
            file_size_bytes=1024,
            library_id=uuid4(),
            scope_type="drive",
            drive_id=None,
        )

        call_kwargs = mock_client.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == settings.sqs_processing_queue_url


# ── SQS failure: DB unaffected ───────────────────────────────────────────────


class TestSQSFailure:
    """SQS send failures must not raise — DB commit is unaffected."""

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_send_failure_swallowed(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.side_effect = Exception("SQS connection refused")
        mock_get_client.return_value = mock_client

        # Must not raise
        publish_processing_job(
            file_id=uuid4(),
            org_id=uuid4(),
            connection_id=uuid4(),
            video_id="gd_test123",
            google_file_id="gfile_abc",
            file_name="test.mp4",
            mime_type="video/mp4",
            file_size_bytes=1024,
            library_id=uuid4(),
            scope_type="drive",
            drive_id=None,
        )

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_enrichment_failure_swallowed(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.side_effect = Exception("SQS timeout")
        mock_get_client.return_value = mock_client

        # Must not raise
        publish_enrichment_jobs(
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_test123",
            keyframe_s3_prefix="s3://prefix/",
            audio_s3_key="s3://audio.wav",
        )

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_partial_failure_continues(self, mock_settings, mock_get_client):
        """If caption SQS send fails, OCR and STT sends should still be attempted."""
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        # First call (caption) fails, second (ocr) and third (stt) succeed
        mock_client.send_message.side_effect = [
            Exception("SQS error"),
            {"MessageId": "msg-ok-1"},
            {"MessageId": "msg-ok-2"},
            {"MessageId": "msg-ok-3"},
            {"MessageId": "msg-ok-4"},
        ]
        mock_get_client.return_value = mock_client

        # Must not raise
        publish_enrichment_jobs(
            file_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_test123",
            keyframe_s3_prefix="s3://prefix/",
            audio_s3_key="s3://audio.wav",
        )

        # All 5 sends attempted despite first failure
        assert mock_client.send_message.call_count == 5


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_empty_queue_url_skips_send(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(
            sqs_enabled=True,
            sqs_processing_queue_url="",
        )
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        publish_processing_job(
            file_id=uuid4(),
            org_id=uuid4(),
            connection_id=uuid4(),
            video_id="gd_test123",
            google_file_id="gfile_abc",
            file_name="test.mp4",
            mime_type="video/mp4",
            file_size_bytes=1024,
            library_id=uuid4(),
            scope_type="drive",
            drive_id=None,
        )

        mock_client.send_message.assert_not_called()

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_unknown_job_type_skips_send(self, mock_settings, mock_get_client):
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        _publish("nonexistent_type", {"file_id": "abc"})

        mock_client.send_message.assert_not_called()

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_file_size_none_serialized(self, mock_settings, mock_get_client):
        """file_size_bytes=None should be serialized as JSON null."""
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-006"}
        mock_get_client.return_value = mock_client

        publish_processing_job(
            file_id=uuid4(),
            org_id=uuid4(),
            connection_id=uuid4(),
            video_id="gd_test123",
            google_file_id="gfile_abc",
            file_name="test.mp4",
            mime_type="video/mp4",
            file_size_bytes=None,
            library_id=uuid4(),
            scope_type="drive",
            drive_id=None,
        )

        body = json.loads(mock_client.send_message.call_args[1]["MessageBody"])
        assert body["file_size_bytes"] is None
        assert body["drive_id"] is None