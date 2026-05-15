"""Tests for SQS shorts render job publishing."""

import json
import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.sqs_producer import (
    _QUEUE_URL_ATTRS,
    _publish,
    QueuePublishError,
    publish_shorts_render_job,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Build a mock Settings object with SQS fields."""
    defaults = {
        "sqs_enabled": False,
        "queue_backend": "sqs",
        "sqs_endpoint_url": "",
        "sqs_region": "ap-northeast-2",
        "sqs_shorts_render_queue_url": "http://localhost:9324/000000000000/heimdex-shorts-render-queue",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _sample_input_spec():
    return {
        "video_id": "gd_test123",
        "scenes": [{"scene_id": "s1", "start": 0.0, "end": 5.0}],
        "output_format": "mp4",
    }


# ── Happy path: SQS enabled ──────────────────────────────────────────────────


class TestShortsRenderEnabled:
    """When sqs_enabled=True, verify publish_shorts_render_job sends correctly."""

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_send_message_called(self, mock_settings, mock_get_client):
        """publish_shorts_render_job() with sqs_enabled=True calls send_message."""
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-shorts-001"}
        mock_get_client.return_value = mock_client

        publish_shorts_render_job(
            job_id=uuid4(),
            org_id=uuid4(),
            video_id="gd_test123",
            input_spec=_sample_input_spec(),
        )

        mock_client.send_message.assert_called_once()

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_message_body_format(self, mock_settings, mock_get_client):
        """Message body contains version, type, job_id, org_id, input_spec, timestamp."""
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-shorts-002"}
        mock_get_client.return_value = mock_client

        job_id = uuid4()
        org_id = uuid4()
        spec = _sample_input_spec()

        publish_shorts_render_job(
            job_id=job_id,
            org_id=org_id,
            video_id="gd_test123",
            input_spec=spec,
        )

        call_kwargs = mock_client.send_message.call_args[1]
        body = json.loads(call_kwargs["MessageBody"])
        assert body["version"] == "1"
        assert body["type"] == "shorts_render.job_created"
        assert body["job_id"] == str(job_id)
        assert body["org_id"] == str(org_id)
        assert body["input_spec"] == spec
        assert "timestamp" in body

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_message_attributes(self, mock_settings, mock_get_client):
        """MessageAttributes include job_type='shorts_render', org_id, source='api'."""
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-shorts-003"}
        mock_get_client.return_value = mock_client

        org_id = uuid4()
        publish_shorts_render_job(
            job_id=uuid4(),
            org_id=org_id,
            video_id="gd_test123",
            input_spec=_sample_input_spec(),
        )

        call_kwargs = mock_client.send_message.call_args[1]
        attrs = call_kwargs["MessageAttributes"]
        assert attrs["job_type"]["StringValue"] == "shorts_render"
        assert attrs["org_id"]["StringValue"] == str(org_id)
        assert attrs["source"]["StringValue"] == "api"


# ── Disabled / no queue URL ──────────────────────────────────────────────────


class TestShortsRenderDisabled:
    """Required render publishes fail loudly when queue config is invalid."""

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_raises_when_disabled(self, mock_settings, mock_get_client):
        """sqs_enabled=False -> QueuePublishError."""
        mock_settings.return_value = _make_settings(sqs_enabled=False)

        with pytest.raises(QueuePublishError):
            publish_shorts_render_job(
                job_id=uuid4(),
                org_id=uuid4(),
                video_id="gd_test123",
                input_spec=_sample_input_spec(),
            )

        mock_get_client.assert_not_called()

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_raises_when_queue_url_empty(self, mock_settings, mock_get_client):
        """sqs_shorts_render_queue_url='' -> QueuePublishError."""
        mock_settings.return_value = _make_settings(
            sqs_enabled=True,
            sqs_shorts_render_queue_url="",
        )
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with pytest.raises(QueuePublishError):
            publish_shorts_render_job(
                job_id=uuid4(),
                org_id=uuid4(),
                video_id="gd_test123",
                input_spec=_sample_input_spec(),
            )

        mock_client.send_message.assert_not_called()


# ── Fire-and-forget (failure swallowed) ──────────────────────────────────────


class TestShortsRenderFailure:
    """Required render publishes raise on SQS send failures."""

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_send_failure_raises(self, mock_settings, mock_get_client):
        """SQS send_message raises exception -> QueuePublishError."""
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.side_effect = Exception("SQS connection refused")
        mock_get_client.return_value = mock_client

        with pytest.raises(QueuePublishError):
            publish_shorts_render_job(
                job_id=uuid4(),
                org_id=uuid4(),
                video_id="gd_test123",
                input_spec=_sample_input_spec(),
            )

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_best_effort_publish_still_swallows(self, mock_settings, mock_get_client):
        """The shared best-effort helper keeps its old fire-and-forget contract."""
        mock_settings.return_value = _make_settings(sqs_enabled=True)
        mock_client = MagicMock()
        mock_client.send_message.side_effect = Exception("SQS connection refused")
        mock_get_client.return_value = mock_client

        _publish("shorts_render", {"org_id": str(uuid4())}, "dedup")


# ── Deduplication & mapping ──────────────────────────────────────────────────


class TestShortsRenderDedup:
    """Deduplication ID and queue mapping."""

    @patch("app.sqs_producer._get_sqs_client")
    @patch("app.sqs_producer.get_settings")
    def test_dedup_id_on_fifo_queue(self, mock_settings, mock_get_client):
        """Deduplication ID format: {job_id}:shorts_render:{minute} on FIFO queue."""
        mock_settings.return_value = _make_settings(
            sqs_enabled=True,
            sqs_shorts_render_queue_url="https://sqs.ap-northeast-2.amazonaws.com/123/heimdex-shorts-render-queue.fifo",
        )
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-fifo-shorts"}
        mock_get_client.return_value = mock_client

        job_id = uuid4()
        publish_shorts_render_job(
            job_id=job_id,
            org_id=uuid4(),
            video_id="gd_test123",
            input_spec=_sample_input_spec(),
        )

        call_kwargs = mock_client.send_message.call_args[1]
        assert "MessageDeduplicationId" in call_kwargs
        dedup = call_kwargs["MessageDeduplicationId"]
        assert dedup.startswith(str(job_id))
        assert ":shorts_render:" in dedup

    def test_queue_url_attr_mapping(self):
        """_QUEUE_URL_ATTRS['shorts_render'] == 'sqs_shorts_render_queue_url'."""
        assert _QUEUE_URL_ATTRS["shorts_render"] == "sqs_shorts_render_queue_url"


# ── Config loading ───────────────────────────────────────────────────────────


class TestShortsRenderConfig:
    """Config loads sqs_shorts_render_queue_url from env."""

    def test_config_loads_queue_url_from_env(self):
        """Settings.sqs_shorts_render_queue_url populated from environment."""
        from app.config import Settings

        url = "http://elasticmq:9324/queue/heimdex-shorts-render-queue"
        with patch.dict(os.environ, {"SQS_SHORTS_RENDER_QUEUE_URL": url}):
            s = Settings(
                database_url="postgresql+asyncpg://x:x@localhost/x",
                database_url_sync="postgresql://x:x@localhost/x",
            )
            assert s.sqs_shorts_render_queue_url == url
