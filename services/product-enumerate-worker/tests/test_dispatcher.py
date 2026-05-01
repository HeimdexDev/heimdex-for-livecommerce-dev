"""Tests for the dispatcher's routing + last-ditch fail callback.

Mirrors product-track-worker/tests/test_dispatcher.py. Adds explicit
coverage for:

* F1 — SDK now passes ``QueueMessage``, not raw dict/string. Pre-fix
  the dispatcher fell through ``isinstance(message, str)`` and would
  have crashed on the first real SQS message.
* F2 — malformed bodies / unknown ``type`` no longer silently ack
  (which deleted the message without retry, DLQ, or /fail).
* F3 — ``_try_fail_callback`` MUST construct ``ApiClient`` with
  ``settings.drive_api_base_url`` only — never with a
  ``callback_base_url`` from the SQS body.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from heimdex_worker_sdk.queue_client import QueueMessage
from heimdex_worker_sdk.sqs_consumer import InvalidMessageError

from src.dispatcher import dispatch
from src.openai_vlm import OpenAIVlmClient
from src.settings import WorkerSettings


def _settings() -> WorkerSettings:
    return WorkerSettings(
        sqs_product_enumerate_queue_url="https://sqs.test/q",
        drive_internal_api_key="t",
        drive_api_base_url="http://api.internal:8000",
        worker_id="test-worker",
        product_v2_enabled=True,
        openai_api_key="sk-test",
    )


def _vlm() -> MagicMock:
    return MagicMock(spec=OpenAIVlmClient)


def _qm(body: dict) -> QueueMessage:
    """Wrap a body dict in the SDK's actual delivery shape."""
    return QueueMessage(
        message_id="m1",
        ack_id="a1",
        body=body,
        receive_count=1,
    )


def test_dispatch_routes_enumerate_job_to_handler():
    body = {"type": "product.enumerate_job", "job_id": str(uuid4())}
    with patch("src.dispatcher.handle_enumerate_job") as h:
        dispatch(body, settings=_settings(), vlm_client=_vlm())
        h.assert_called_once()


def test_dispatch_parses_string_body():
    body = json.dumps({"type": "product.enumerate_job", "job_id": str(uuid4())})
    with patch("src.dispatcher.handle_enumerate_job") as h:
        dispatch(body, settings=_settings(), vlm_client=_vlm())
        h.assert_called_once()


def test_dispatch_handles_queue_message():
    """F1: SDK ConsumerLoop now passes ``QueueMessage``. The
    enumerate-worker has been deployed since 2026-04-29 with this
    bug latent — flag-gated off, so no real SQS message has hit it
    yet."""
    body = {"type": "product.enumerate_job", "job_id": str(uuid4())}
    with patch("src.dispatcher.handle_enumerate_job") as h:
        dispatch(_qm(body), settings=_settings(), vlm_client=_vlm())
    h.assert_called_once()
    assert h.call_args.kwargs["message"] == body


def test_dispatch_unknown_type_with_job_id_raises_invalid_message():
    """A misrouted message (``product.track_job`` on the enumerate
    queue) should NOT trigger /fail — the worker doesn't own the
    lease so /fail would 409. Raise ``InvalidMessageError`` so the
    SDK ack-deletes via poison-pill semantics."""
    body = {"type": "product.track_job", "job_id": str(uuid4())}
    fake_api = MagicMock()
    with patch("src.dispatcher.handle_enumerate_job") as h, patch(
        "src.dispatcher.ApiClient", return_value=fake_api
    ):
        with pytest.raises(InvalidMessageError):
            dispatch(body, settings=_settings(), vlm_client=_vlm())
    h.assert_not_called()
    fake_api.fail.assert_not_called()


def test_dispatch_unknown_type_without_job_id_raises_invalid_message():
    body = {"type": "product.unknown"}
    with patch("src.dispatcher.handle_enumerate_job") as h:
        with pytest.raises(InvalidMessageError):
            dispatch(body, settings=_settings(), vlm_client=_vlm())
    h.assert_not_called()


def test_dispatch_invalid_json_string_raises_invalid_message():
    with patch("src.dispatcher.handle_enumerate_job") as h:
        with pytest.raises(InvalidMessageError):
            dispatch("not-json-{", settings=_settings(), vlm_client=_vlm())
    h.assert_not_called()


def test_dispatch_non_object_json_raises_invalid_message():
    with patch("src.dispatcher.handle_enumerate_job") as h:
        with pytest.raises(InvalidMessageError):
            dispatch("[1, 2, 3]", settings=_settings(), vlm_client=_vlm())
    h.assert_not_called()


def test_dispatch_calls_fail_callback_on_handler_exception():
    job_id = uuid4()
    body = {"type": "product.enumerate_job", "job_id": str(job_id)}
    fake_api = MagicMock()
    with patch(
        "src.dispatcher.handle_enumerate_job", side_effect=RuntimeError("boom")
    ):
        with patch("src.dispatcher.ApiClient", return_value=fake_api) as ApiClient:
            dispatch(body, settings=_settings(), vlm_client=_vlm())
    fake_api.fail.assert_called_once()
    fail_kwargs = fake_api.fail.call_args.kwargs
    assert fail_kwargs["error_code"] == "internal_error"
    assert "boom" in fail_kwargs["error_message"]
    assert ApiClient.call_args.kwargs["base_url"] == "http://api.internal:8000"


def test_dispatch_reraises_when_fail_callback_also_fails():
    """If /fail itself fails (api outage), the dispatcher re-raises
    the original exception so the SDK leaves the SQS message visible
    for redelivery instead of silently ack-deleting it."""
    body = {"type": "product.enumerate_job", "job_id": str(uuid4())}
    fake_api = MagicMock()
    fake_api.fail.side_effect = RuntimeError("api also down")
    with patch(
        "src.dispatcher.handle_enumerate_job", side_effect=RuntimeError("boom")
    ):
        with patch("src.dispatcher.ApiClient", return_value=fake_api):
            with pytest.raises(RuntimeError, match="boom"):
                dispatch(body, settings=_settings(), vlm_client=_vlm())


def test_dispatch_fail_callback_ignores_callback_base_url_from_body():
    """SECURITY (F3): a producer setting ``callback_base_url`` in the
    SQS body MUST NOT redirect bearer-authenticated /fail calls.
    Pre-fix, the dispatcher built ApiClient with
    ``body['callback_base_url'] or settings.drive_api_base_url`` — an
    attacker who could enqueue could exfiltrate the bearer token."""
    body = {
        "type": "product.enumerate_job",
        "job_id": str(uuid4()),
        "callback_base_url": "https://attacker.example.com",
    }
    fake_api = MagicMock()
    with patch(
        "src.dispatcher.handle_enumerate_job", side_effect=RuntimeError("boom")
    ):
        with patch("src.dispatcher.ApiClient", return_value=fake_api) as ApiClient:
            dispatch(body, settings=_settings(), vlm_client=_vlm())
    assert ApiClient.call_args.kwargs["base_url"] == "http://api.internal:8000"
    assert "attacker" not in ApiClient.call_args.kwargs["base_url"]
