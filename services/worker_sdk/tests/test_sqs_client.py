"""Tests for SQSJobClient — SQS wrapper for job queue operations."""

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from heimdex_worker_sdk.sqs_client import SQSJobClient, SQSMessage


QUEUE_URL = "http://localhost:9324/000000000000/heimdex-caption-queue"


@pytest.fixture
def mock_boto_client():
    with patch("heimdex_worker_sdk.sqs_client.boto3") as mock_boto3:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        yield mock_boto3, mock_client


class TestInit:
    def test_creates_client_with_region(self, mock_boto_client):
        mock_boto3, _ = mock_boto_client
        SQSJobClient(QUEUE_URL, region="ap-northeast-2")
        mock_boto3.client.assert_called_once_with(
            "sqs", region_name="ap-northeast-2"
        )

    def test_passes_endpoint_url_for_elasticmq(self, mock_boto_client):
        mock_boto3, _ = mock_boto_client
        SQSJobClient(
            QUEUE_URL,
            region="ap-northeast-2",
            endpoint_url="http://elasticmq:9324",
        )
        mock_boto3.client.assert_called_once_with(
            "sqs",
            region_name="ap-northeast-2",
            endpoint_url="http://elasticmq:9324",
        )

    def test_omits_endpoint_url_when_empty_string(self, mock_boto_client):
        mock_boto3, _ = mock_boto_client
        SQSJobClient(QUEUE_URL, region="ap-northeast-2", endpoint_url="")
        mock_boto3.client.assert_called_once_with(
            "sqs", region_name="ap-northeast-2"
        )

    def test_omits_endpoint_url_when_none(self, mock_boto_client):
        mock_boto3, _ = mock_boto_client
        SQSJobClient(QUEUE_URL, region="ap-northeast-2", endpoint_url=None)
        mock_boto3.client.assert_called_once_with(
            "sqs", region_name="ap-northeast-2"
        )


class TestReceiveJobs:
    def test_maps_response_to_sqs_message(self, mock_boto_client):
        _, mock_client = mock_boto_client
        file_id = str(uuid4())
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "msg-001",
                    "ReceiptHandle": "handle-001",
                    "Body": json.dumps({"file_id": file_id, "job_type": "caption"}),
                    "Attributes": {"ApproximateReceiveCount": "3"},
                }
            ]
        }
        client = SQSJobClient(QUEUE_URL)
        messages = client.receive_jobs(max_messages=1, wait_time=20, visibility_timeout=60)

        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, SQSMessage)
        assert msg.message_id == "msg-001"
        assert msg.receipt_handle == "handle-001"
        assert msg.body == {"file_id": file_id, "job_type": "caption"}
        assert msg.receive_count == 3

        mock_client.receive_message.assert_called_once_with(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=60,
            AttributeNames=["ApproximateReceiveCount"],
            MessageAttributeNames=["All"],
        )

    def test_returns_empty_list_when_no_messages(self, mock_boto_client):
        _, mock_client = mock_boto_client
        mock_client.receive_message.return_value = {}
        client = SQSJobClient(QUEUE_URL)
        assert client.receive_jobs() == []

    def test_defaults_receive_count_to_1(self, mock_boto_client):
        _, mock_client = mock_boto_client
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "msg-002",
                    "ReceiptHandle": "handle-002",
                    "Body": json.dumps({"ok": True}),
                    "Attributes": {},
                }
            ]
        }
        client = SQSJobClient(QUEUE_URL)
        messages = client.receive_jobs()
        assert messages[0].receive_count == 1

    def test_skips_invalid_json_body(self, mock_boto_client):
        _, mock_client = mock_boto_client
        mock_client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "msg-bad",
                    "ReceiptHandle": "handle-bad",
                    "Body": "not-json{{",
                    "Attributes": {},
                },
                {
                    "MessageId": "msg-good",
                    "ReceiptHandle": "handle-good",
                    "Body": json.dumps({"ok": True}),
                    "Attributes": {},
                },
            ]
        }
        client = SQSJobClient(QUEUE_URL)
        messages = client.receive_jobs(max_messages=10)
        assert len(messages) == 1
        assert messages[0].message_id == "msg-good"


class TestCompleteJob:
    def test_calls_delete_message(self, mock_boto_client):
        _, mock_client = mock_boto_client
        client = SQSJobClient(QUEUE_URL)
        client.complete_job("receipt-abc")

        mock_client.delete_message.assert_called_once_with(
            QueueUrl=QUEUE_URL,
            ReceiptHandle="receipt-abc",
        )


class TestExtendVisibility:
    def test_calls_change_message_visibility(self, mock_boto_client):
        _, mock_client = mock_boto_client
        client = SQSJobClient(QUEUE_URL)
        client.extend_visibility("receipt-abc", timeout=120)

        mock_client.change_message_visibility.assert_called_once_with(
            QueueUrl=QUEUE_URL,
            ReceiptHandle="receipt-abc",
            VisibilityTimeout=120,
        )


class TestSendJob:
    def test_serializes_body_and_returns_message_id(self, mock_boto_client):
        _, mock_client = mock_boto_client
        mock_client.send_message.return_value = {"MessageId": "sent-001"}

        client = SQSJobClient(QUEUE_URL)
        body = {"file_id": str(uuid4()), "job_type": "stt"}
        result = client.send_job(body)

        assert result == "sent-001"
        call_kwargs = mock_client.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == QUEUE_URL
        assert json.loads(call_kwargs["MessageBody"]) == body
        assert "MessageDeduplicationId" not in call_kwargs

    def test_passes_deduplication_id_when_provided(self, mock_boto_client):
        _, mock_client = mock_boto_client
        mock_client.send_message.return_value = {"MessageId": "sent-002"}

        client = SQSJobClient(QUEUE_URL)
        client.send_job({"ok": True}, deduplication_id="dedup-123")

        call_kwargs = mock_client.send_message.call_args[1]
        assert call_kwargs["MessageDeduplicationId"] == "dedup-123"

    def test_omits_deduplication_id_when_none(self, mock_boto_client):
        _, mock_client = mock_boto_client
        mock_client.send_message.return_value = {"MessageId": "sent-003"}

        client = SQSJobClient(QUEUE_URL)
        client.send_job({"ok": True}, deduplication_id=None)

        call_kwargs = mock_client.send_message.call_args[1]
        assert "MessageDeduplicationId" not in call_kwargs


class TestSQSMessageDataclass:
    def test_frozen(self):
        msg = SQSMessage(
            message_id="m1",
            receipt_handle="r1",
            body={"key": "val"},
            receive_count=1,
        )
        with pytest.raises(AttributeError):
            msg.message_id = "m2"
