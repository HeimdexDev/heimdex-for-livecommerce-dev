"""Tests for the dispatcher's routing + last-ditch fail callback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.dispatcher import dispatch
from src.settings import WorkerSettings


def _settings() -> WorkerSettings:
    return WorkerSettings(
        sqs_product_track_queue_url="https://sqs.test/q",
        drive_internal_api_key="t",
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


def test_dispatch_ignores_unknown_type():
    body = {"type": "product.enumerate_job", "job_id": str(uuid4())}
    with patch("src.dispatcher.handle_track_job") as h:
        dispatch(body, settings=_settings())
        h.assert_not_called()


def test_dispatch_swallows_invalid_json_string_body():
    """A non-JSON string body should not crash the dispatcher — log
    + ignore. The SQS consumer then DLQs the message after
    maxReceiveCount=3."""
    with patch("src.dispatcher.handle_track_job") as h:
        dispatch("not-json-{", settings=_settings())
        h.assert_not_called()


def test_dispatch_calls_fail_callback_on_handler_exception():
    """A raised exception in the handler triggers a /fail HTTP call
    so the user-facing UI surfaces the error rather than the job
    hanging until lease expiry."""
    job_id = uuid4()
    body = {
        "type": "product.track_job",
        "job_id": str(job_id),
        "callback_base_url": "https://api.test",
    }
    fake_api = MagicMock()
    with patch("src.dispatcher.handle_track_job", side_effect=RuntimeError("boom")):
        with patch("src.dispatcher.ApiClient", return_value=fake_api):
            dispatch(body, settings=_settings())
    fake_api.fail.assert_called_once()
    fail_kwargs = fake_api.fail.call_args.kwargs
    assert fail_kwargs["error_code"] == "internal_error"
    assert "boom" in fail_kwargs["error_message"]


def test_dispatch_fail_callback_swallows_its_own_exception():
    """If even the /fail call fails, dispatcher must not raise — the
    SQS consumer is the last line of defense (DLQ after retries)."""
    body = {
        "type": "product.track_job",
        "job_id": str(uuid4()),
        "callback_base_url": "https://api.test",
    }
    fake_api = MagicMock()
    fake_api.fail.side_effect = RuntimeError("api also down")
    with patch("src.dispatcher.handle_track_job", side_effect=RuntimeError("boom")):
        with patch("src.dispatcher.ApiClient", return_value=fake_api):
            # Should NOT raise.
            dispatch(body, settings=_settings())
