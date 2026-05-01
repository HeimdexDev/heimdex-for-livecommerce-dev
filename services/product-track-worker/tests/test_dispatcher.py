"""Tests for the dispatcher's routing + last-ditch fail callback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from heimdex_worker_sdk.queue_client import QueueMessage
from heimdex_worker_sdk.sqs_consumer import InvalidMessageError

from src.dispatcher import dispatch
from src.settings import WorkerSettings


def _qm(body: dict) -> QueueMessage:
    """Wrap a body dict in the SDK's actual delivery shape."""
    return QueueMessage(
        message_id="m1",
        ack_id="a1",
        body=body,
        receive_count=1,
    )


def _settings() -> WorkerSettings:
    return WorkerSettings(
        sqs_product_track_queue_url="https://sqs.test/q",
        drive_internal_api_key="t",
        drive_api_base_url="http://api.internal:8000",
        worker_id="test-worker",
        product_v2_enabled=True,
    )


def test_dispatch_routes_track_job_to_handler():
    body = {"type": "product.track_job", "job_id": str(uuid4())}
    with patch("src.dispatcher.handle_track_job") as h:
        dispatch(body, settings=_settings())
        h.assert_called_once()


def test_dispatch_parses_string_body():
    body = json.dumps({"type": "product.track_job", "job_id": str(uuid4())})
    with patch("src.dispatcher.handle_track_job") as h:
        dispatch(body, settings=_settings())
        h.assert_called_once()


def test_dispatch_handles_queue_message():
    """F1: SDK ConsumerLoop now passes ``QueueMessage`` to the
    callback. Pre-fix, the dispatcher's ``isinstance(message, str)``
    branch fell through and crashed on ``body.get("type")``. The
    first real SQS message would have failed."""
    body = {"type": "product.track_job", "job_id": str(uuid4())}
    with patch("src.dispatcher.handle_track_job") as h:
        dispatch(_qm(body), settings=_settings())
    h.assert_called_once()
    # The handler receives the inner dict, not the wrapper.
    assert h.call_args.kwargs["message"] == body


def test_dispatch_unknown_type_with_real_job_id_raises_for_dlq():
    """A misrouted message (``product.enumerate_job`` on the track
    queue) with a real ``job_id`` MUST NOT poison-pill ack-delete
    (which would orphan the api row at ``queued`` forever) and MUST
    NOT call /fail (worker doesn't own the lease). Instead, raise a
    generic exception so the SDK leaves the message visible — SQS
    redelivers, eventually DLQ, operator notices."""
    from src.dispatcher import DispatchUnknownTypeError

    body = {"type": "product.enumerate_job", "job_id": str(uuid4())}
    fake_api = MagicMock()
    with patch("src.dispatcher.handle_track_job") as h, patch(
        "src.dispatcher.ApiClient", return_value=fake_api
    ):
        with pytest.raises(DispatchUnknownTypeError):
            dispatch(body, settings=_settings())
    h.assert_not_called()
    fake_api.fail.assert_not_called()


def test_dispatch_unknown_type_no_job_id_raises_invalid_message():
    """A truly malformed message (no parseable ``job_id``) IS the
    poison-pill case — there's no api row to orphan. Raise
    ``InvalidMessageError`` so the SDK ack-deletes with structured
    ``sqs_invalid_message_deleted`` log."""
    body = {"type": "product.unknown.event"}  # no job_id at all
    fake_api = MagicMock()
    with patch("src.dispatcher.handle_track_job") as h, patch(
        "src.dispatcher.ApiClient", return_value=fake_api
    ):
        with pytest.raises(InvalidMessageError):
            dispatch(body, settings=_settings())
    h.assert_not_called()
    fake_api.fail.assert_not_called()


def test_dispatch_unknown_type_without_job_id_raises_invalid_message():
    """F2: when the body lacks a parseable ``job_id``, /fail isn't
    possible. Raise ``InvalidMessageError`` so the SDK auto-deletes
    the poison pill with a structured ``sqs_invalid_message_deleted``
    log instead of silently succeeding."""
    body = {"type": "product.unknown"}  # no job_id
    with patch("src.dispatcher.handle_track_job") as h:
        with pytest.raises(InvalidMessageError):
            dispatch(body, settings=_settings())
    h.assert_not_called()


def test_dispatch_invalid_json_string_raises_invalid_message():
    """F2: pre-fix, a non-JSON body was silently swallowed and the
    SDK ack-deleted. Post-fix, raise ``InvalidMessageError`` so the
    SDK logs ``sqs_invalid_message_deleted`` with the message id +
    receive count before deleting."""
    with patch("src.dispatcher.handle_track_job") as h:
        with pytest.raises(InvalidMessageError):
            dispatch("not-json-{", settings=_settings())
    h.assert_not_called()


def test_dispatch_non_object_json_raises_invalid_message():
    """A JSON array (or scalar) body can't carry a job — same poison
    pill semantics as malformed JSON."""
    with patch("src.dispatcher.handle_track_job") as h:
        with pytest.raises(InvalidMessageError):
            dispatch("[1, 2, 3]", settings=_settings())
    h.assert_not_called()


def test_dispatch_calls_fail_callback_on_handler_exception():
    """A raised exception in the handler triggers a /fail HTTP call
    so the user-facing UI surfaces the error rather than the job
    hanging until lease expiry."""
    job_id = uuid4()
    body = {
        "type": "product.track_job",
        "job_id": str(job_id),
    }
    fake_api = MagicMock()
    with patch("src.dispatcher.handle_track_job", side_effect=RuntimeError("boom")):
        with patch("src.dispatcher.ApiClient", return_value=fake_api) as ApiClient:
            dispatch(body, settings=_settings())
    fake_api.fail.assert_called_once()
    fail_kwargs = fake_api.fail.call_args.kwargs
    assert fail_kwargs["error_code"] == "internal_error"
    assert "boom" in fail_kwargs["error_message"]
    # F3: API base URL comes from settings, never the body.
    assert ApiClient.call_args.kwargs["base_url"] == "http://api.internal:8000"


def test_dispatch_acks_when_fail_callback_returns_409_terminal():
    """When the api's /fail returns 409 (lease lost or job missing),
    the job is already in a terminal state on the api side —
    redelivering the SQS message can't help. Dispatcher MUST treat
    this as success and ack-delete (not re-raise into DLQ retry).
    Pre-fix this would have re-raised, burning receive-count and
    eventually DLQ'ing benign duplicates."""
    import httpx

    body = {"type": "product.track_job", "job_id": str(uuid4())}
    request = httpx.Request("POST", "http://api/internal/products/x/fail")
    response = httpx.Response(409, request=request)
    fake_api = MagicMock()
    fake_api.fail.side_effect = httpx.HTTPStatusError(
        "409 Conflict — lease lost or job missing",
        request=request,
        response=response,
    )
    with patch("src.dispatcher.handle_track_job", side_effect=RuntimeError("boom")):
        with patch("src.dispatcher.ApiClient", return_value=fake_api):
            # MUST NOT raise.
            dispatch(body, settings=_settings())
    fake_api.fail.assert_called_once()


def test_dispatch_reraises_when_fail_callback_also_fails():
    """If the /fail call itself fails (api outage), the dispatcher
    re-raises the original handler exception. SDK's
    ``ConsumerLoop._process_with_heartbeat`` catches that and leaves
    the SQS message visible — it'll be redelivered after the
    visibility timeout, eventually DLQ'd if the api stays down.

    Pre-fix this swallowed the second failure and ``dispatch()``
    returned normally → SDK ack-deleted the message → tracking job
    stuck in ``tracking`` with no retry path."""
    body = {
        "type": "product.track_job",
        "job_id": str(uuid4()),
    }
    fake_api = MagicMock()
    fake_api.fail.side_effect = RuntimeError("api also down")
    with patch("src.dispatcher.handle_track_job", side_effect=RuntimeError("boom")):
        with patch("src.dispatcher.ApiClient", return_value=fake_api):
            with pytest.raises(RuntimeError, match="boom"):
                dispatch(body, settings=_settings())


def test_dispatch_fail_callback_ignores_callback_base_url_from_body():
    """SECURITY (F3): a producer setting ``callback_base_url`` in the
    SQS body MUST NOT redirect bearer-authenticated /fail calls.
    Pre-fix, the dispatcher built ApiClient with
    ``body['callback_base_url'] or settings.drive_api_base_url`` — an
    attacker who could enqueue could exfiltrate the bearer token."""
    body = {
        "type": "product.track_job",
        "job_id": str(uuid4()),
        # Attacker-controlled URL planted in the body.
        "callback_base_url": "https://attacker.example.com",
    }
    fake_api = MagicMock()
    with patch("src.dispatcher.handle_track_job", side_effect=RuntimeError("boom")):
        with patch("src.dispatcher.ApiClient", return_value=fake_api) as ApiClient:
            dispatch(body, settings=_settings())
    # ApiClient must be constructed with the settings URL, not the body.
    assert ApiClient.call_args.kwargs["base_url"] == "http://api.internal:8000"
    assert "attacker" not in ApiClient.call_args.kwargs["base_url"]
