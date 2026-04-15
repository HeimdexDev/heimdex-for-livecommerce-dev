"""Unit tests for :mod:`src.dispatcher`.

Scope: message-type routing only. Does not exercise the actual task
handlers — those are stubbed via monkeypatch so the tests don't need
torch, transformers, or ffmpeg installed in the test venv.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest


def _fake_message(body: dict[str, Any]) -> SimpleNamespace:
    """Mimic the attribute shape of an SQS boto3 Message."""
    return SimpleNamespace(body=json.dumps(body))


@pytest.fixture
def fake_task_modules(monkeypatch):
    """Install stub ``src.tasks.blur_video`` and ``src.tasks.export_layer``
    modules so the dispatcher can route without pulling in heavy deps.
    """
    blur_calls: list[dict[str, Any]] = []
    export_calls: list[dict[str, Any]] = []

    blur_video = SimpleNamespace(
        sqs_to_blur_claim=lambda msg: {"parsed": "blur", "msg": msg},
        process_blur_message=lambda **kwargs: blur_calls.append(kwargs),
    )
    export_layer = SimpleNamespace(
        sqs_to_export_ref=lambda msg: {"parsed": "export", "msg": msg},
        process_export_message=lambda **kwargs: export_calls.append(kwargs),
    )

    monkeypatch.setitem(sys.modules, "src.tasks.blur_video", blur_video)
    monkeypatch.setitem(sys.modules, "src.tasks.export_layer", export_layer)

    return SimpleNamespace(blur_calls=blur_calls, export_calls=export_calls)


def test_dispatch_routes_blur_job_created(fake_task_modules):
    from src.dispatcher import dispatch

    msg = _fake_message({
        "type": "blur.job_created",
        "job_id": "00000000-0000-0000-0000-000000000001",
        "org_id": "00000000-0000-0000-0000-000000000002",
        "file_id": "00000000-0000-0000-0000-000000000003",
        "video_id": "vid-abc",
    })
    dispatch(
        msg,
        api_base_url="http://api",
        internal_api_key="k",
        settings=SimpleNamespace(),
        pipeline=SimpleNamespace(),
    )
    assert len(fake_task_modules.blur_calls) == 1
    assert len(fake_task_modules.export_calls) == 0
    assert fake_task_modules.blur_calls[0]["api_base_url"] == "http://api"
    assert "claim_ref" in fake_task_modules.blur_calls[0]


def test_dispatch_routes_blur_export_created(fake_task_modules):
    from src.dispatcher import dispatch

    msg = _fake_message({
        "type": "blur.export_created",
        "export_id": "00000000-0000-0000-0000-0000000000aa",
        "blur_job_id": "00000000-0000-0000-0000-0000000000bb",
        "org_id": "00000000-0000-0000-0000-0000000000cc",
        "video_id": "vid-xyz",
    })
    dispatch(
        msg,
        api_base_url="http://api",
        internal_api_key="k",
        settings=SimpleNamespace(),
        pipeline=SimpleNamespace(),
    )
    assert len(fake_task_modules.export_calls) == 1
    assert len(fake_task_modules.blur_calls) == 0
    assert "export_ref" in fake_task_modules.export_calls[0]


def test_dispatch_unknown_type_raises(fake_task_modules):
    from src.dispatcher import UnknownMessageType, dispatch

    msg = _fake_message({"type": "something.else", "foo": "bar"})
    with pytest.raises(UnknownMessageType):
        dispatch(
            msg,
            api_base_url="http://api",
            internal_api_key="k",
            settings=SimpleNamespace(),
            pipeline=SimpleNamespace(),
        )
    assert fake_task_modules.blur_calls == []
    assert fake_task_modules.export_calls == []


def test_dispatch_missing_type_raises(fake_task_modules):
    from src.dispatcher import UnknownMessageType, dispatch

    msg = _fake_message({"no_type_field": True})
    with pytest.raises(UnknownMessageType):
        dispatch(
            msg,
            api_base_url="http://api",
            internal_api_key="k",
            settings=SimpleNamespace(),
            pipeline=SimpleNamespace(),
        )


def test_message_type_parses_bytes_body(fake_task_modules):
    """Some SQS clients hand us the body as bytes, not str."""
    from src.dispatcher import message_type

    msg = SimpleNamespace(body=json.dumps({"type": "blur.job_created"}).encode())
    assert message_type(msg) == "blur.job_created"


def test_message_type_parses_dict_message(fake_task_modules):
    """boto3 low-level responses use a dict with a 'Body' key."""
    from src.dispatcher import message_type

    msg = {"Body": json.dumps({"type": "blur.export_created"})}
    assert message_type(msg) == "blur.export_created"
