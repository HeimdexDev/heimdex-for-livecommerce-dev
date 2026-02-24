"""
SQS client for Heimdex job queue operations.

Wraps boto3 SQS to provide a clean interface for workers (consumers)
and the API (producer).  Works against both real AWS SQS and ElasticMQ
(local dev) via the ``endpoint_url`` parameter.

Phase 0: This module is shipped dormant.  No worker or API code calls
it yet.  It will be wired in Phase 1 (producer) and Phase 2 (consumer).
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import boto3

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SQSMessage:
    """A single message received from an SQS queue."""

    message_id: str
    receipt_handle: str
    body: dict[str, Any]
    receive_count: int


class SQSJobClient:
    """Thin wrapper around boto3 SQS for job queue operations.

    Args:
        queue_url: Full SQS queue URL (or ElasticMQ URL).
        region: AWS region (e.g. ``"ap-northeast-2"``).
        endpoint_url: Override endpoint for local dev (ElasticMQ).
            Leave *empty string* or ``None`` for real AWS SQS.
    """

    def __init__(
        self,
        queue_url: str,
        region: str = "ap-northeast-2",
        endpoint_url: Optional[str] = None,
    ) -> None:
        self.queue_url = queue_url
        kwargs: dict[str, Any] = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        self._client = boto3.client("sqs", **kwargs)

    # ── Consumer operations ───────────────────────────────────────────

    def receive_jobs(
        self,
        max_messages: int = 1,
        wait_time: int = 20,
        visibility_timeout: int = 60,
    ) -> list[SQSMessage]:
        """Long-poll the queue for messages.

        Returns an empty list when the wait expires with no messages.
        """
        resp = self._client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_time,
            VisibilityTimeout=visibility_timeout,
            AttributeNames=["ApproximateReceiveCount"],
            MessageAttributeNames=["All"],
        )
        messages: list[SQSMessage] = []
        for raw in resp.get("Messages", []):
            try:
                body = json.loads(raw["Body"])
            except (json.JSONDecodeError, KeyError):
                logger.warning(
                    "sqs_invalid_message_body",
                    extra={"message_id": raw.get("MessageId", "unknown")},
                )
                continue
            messages.append(
                SQSMessage(
                    message_id=raw["MessageId"],
                    receipt_handle=raw["ReceiptHandle"],
                    body=body,
                    receive_count=int(
                        raw.get("Attributes", {}).get(
                            "ApproximateReceiveCount", 1
                        )
                    ),
                )
            )
        return messages

    def complete_job(self, receipt_handle: str) -> None:
        """Delete a successfully processed message from the queue."""
        self._client.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle,
        )

    def extend_visibility(
        self, receipt_handle: str, timeout: int
    ) -> None:
        """Extend the visibility timeout (heartbeat) for an in-flight message."""
        self._client.change_message_visibility(
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=timeout,
        )

    # ── Producer operations ───────────────────────────────────────────

    def send_job(
        self,
        body: dict[str, Any],
        deduplication_id: Optional[str] = None,
    ) -> str:
        """Send a job message to the queue.

        Returns the SQS MessageId.
        """
        kwargs: dict[str, Any] = {
            "QueueUrl": self.queue_url,
            "MessageBody": json.dumps(body, default=str),
        }
        if deduplication_id is not None:
            kwargs["MessageDeduplicationId"] = deduplication_id
        resp = self._client.send_message(**kwargs)
        return resp["MessageId"]
