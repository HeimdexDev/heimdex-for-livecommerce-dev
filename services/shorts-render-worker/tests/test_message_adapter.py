"""Tests for SQS message adapter."""

from types import SimpleNamespace

import pytest

from src.message_adapter import RenderJobMessage, sqs_to_render_job


def _make_message(body: dict) -> SimpleNamespace:
    return SimpleNamespace(body=body)


# --- Test 1: valid message → correct RenderJobMessage ---


def test_sqs_to_render_job_valid():
    msg = _make_message({
        "job_id": "abc-123",
        "org_id": "org-456",
        "input_spec": {"output": {"width": 405}},
    })
    result = sqs_to_render_job(msg)

    assert isinstance(result, RenderJobMessage)
    assert result.job_id == "abc-123"
    assert result.org_id == "org-456"
    assert result.input_spec == {"output": {"width": 405}}


# --- Test 2: missing job_id → KeyError ---


def test_sqs_to_render_job_missing_job_id():
    msg = _make_message({"org_id": "org-456", "input_spec": {}})
    with pytest.raises(KeyError, match="job_id"):
        sqs_to_render_job(msg)


# --- Test 3: missing input_spec → KeyError ---


def test_sqs_to_render_job_missing_input_spec():
    msg = _make_message({"job_id": "abc-123", "org_id": "org-456"})
    with pytest.raises(KeyError, match="input_spec"):
        sqs_to_render_job(msg)


# --- Test 4: dataclass fields accessible ---


def test_render_job_message_fields():
    rjm = RenderJobMessage(job_id="j1", org_id="o1", input_spec={"key": "val"})
    assert rjm.job_id == "j1"
    assert rjm.org_id == "o1"
    assert rjm.input_spec == {"key": "val"}
