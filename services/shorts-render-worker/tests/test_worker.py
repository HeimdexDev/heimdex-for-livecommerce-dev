"""Tests for shorts-render-worker entry point."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.worker import _init_semaphore, _make_sqs_callback


# --- Test 5: _init_semaphore returns Semaphore ---


def test_init_semaphore_returns_semaphore():
    import src.worker as w

    w._semaphore = None  # reset global
    sem = _init_semaphore(2)
    assert isinstance(sem, threading.Semaphore)
    w._semaphore = None  # cleanup


# --- Test 6: _init_semaphore called twice → same instance ---


def test_init_semaphore_singleton():
    import src.worker as w

    w._semaphore = None  # reset global
    sem1 = _init_semaphore(2)
    sem2 = _init_semaphore(4)  # different arg, same instance
    assert sem1 is sem2
    w._semaphore = None  # cleanup


# --- Test 7: _make_sqs_callback returns callable ---


def test_make_sqs_callback_returns_callable():
    api_client = MagicMock()
    settings = MagicMock()

    with patch("src.worker.importlib") as mock_importlib:
        mock_module = MagicMock()
        mock_module.process_render_job = MagicMock()
        mock_importlib.import_module.return_value = mock_module

        cb = _make_sqs_callback(api_client, settings)

    assert callable(cb)


# --- Test 8: callback parses message and calls process_render_job ---


def test_callback_calls_process_render_job():
    api_client = MagicMock()
    settings = MagicMock()
    mock_process = MagicMock()

    with patch("src.worker.importlib") as mock_importlib:
        mock_module = MagicMock()
        mock_module.process_render_job = mock_process
        mock_importlib.import_module.return_value = mock_module

        cb = _make_sqs_callback(api_client, settings)

    message = SimpleNamespace(body={
        "job_id": "j1",
        "org_id": "o1",
        "input_spec": {"output": {}},
    })
    cb(message)

    mock_process.assert_called_once()
    call_kwargs = mock_process.call_args[1]
    assert call_kwargs["api_client"] is api_client
    assert call_kwargs["settings"] is settings
    assert call_kwargs["render_job"].job_id == "j1"


# --- Test 9: worker exits with code 1 when SQS not configured ---


def test_worker_exits_when_sqs_disabled():
    mock_settings = MagicMock()
    mock_settings.log_level = "INFO"
    mock_settings.drive_api_base_url = "http://api:8000"
    mock_settings.drive_internal_api_key = "test-key"
    mock_settings.sqs_consumer_enabled = False
    mock_settings.sqs_shorts_render_queue_url = ""

    with (
        patch("src.worker.importlib") as mock_importlib,
        pytest.raises(SystemExit) as exc_info,
    ):
        mock_settings_mod = MagicMock()
        mock_settings_mod.get_worker_settings.return_value = mock_settings

        mock_api_mod = MagicMock()

        def import_side_effect(name):
            if "settings" in name:
                return mock_settings_mod
            if "internal_api" in name:
                return mock_api_mod
            return MagicMock()

        mock_importlib.import_module.side_effect = import_side_effect

        from src.worker import main
        main()

    assert exc_info.value.code == 1


# --- Test 10: worker exits with code 1 when queue URL empty ---


def test_worker_exits_when_queue_url_empty():
    mock_settings = MagicMock()
    mock_settings.log_level = "INFO"
    mock_settings.drive_api_base_url = "http://api:8000"
    mock_settings.drive_internal_api_key = "test-key"
    mock_settings.sqs_consumer_enabled = True
    mock_settings.sqs_shorts_render_queue_url = ""

    with (
        patch("src.worker.importlib") as mock_importlib,
        pytest.raises(SystemExit) as exc_info,
    ):
        mock_settings_mod = MagicMock()
        mock_settings_mod.get_worker_settings.return_value = mock_settings

        mock_api_mod = MagicMock()

        def import_side_effect(name):
            if "settings" in name:
                return mock_settings_mod
            if "internal_api" in name:
                return mock_api_mod
            return MagicMock()

        mock_importlib.import_module.side_effect = import_side_effect

        from src.worker import main
        main()

    assert exc_info.value.code == 1
