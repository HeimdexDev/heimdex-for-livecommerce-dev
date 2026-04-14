"""Regression tests for ``sqs_producer._wake_gpu_worker``.

These tests close the loop on a latent bug that kept the api-side GPU
wake path silently broken for all workers: the api container's
``pyproject.toml`` did not list ``heimdex-worker-sdk``, every wake call
hit ``ModuleNotFoundError``, and the original bare ``except Exception``
swallowed it. The symptom was "all GPU workers have 5-minute wake
latency" — which no one noticed because drive-worker's cron filled in.

Two layers of coverage:

1. **Importability** — ``import heimdex_worker_sdk.gpu_orchestrator``
   must succeed in whatever environment the API runs. If the dependency
   drops out of ``pyproject.toml``, this test fails immediately. No
   mocks, no stubs — the real import.

2. **Wake dispatch** — ``_wake_gpu_worker`` must actually reach
   ``heimdex_worker_sdk.gpu_orchestrator.ensure_worker_running`` with
   the job type we passed. We mock the SDK's ``ensure_worker_running``
   to prove the fast-path is connected end-to-end, and we exercise the
   ImportError branch by monkeypatching ``sys.modules`` to simulate the
   regression.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def test_heimdex_worker_sdk_importable():
    """Fails the suite if heimdex-worker-sdk ever drops out of
    services/api/pyproject.toml. Catches the regression without
    needing the wake path to execute."""
    import heimdex_worker_sdk.gpu_orchestrator  # noqa: F401
    from heimdex_worker_sdk.gpu_orchestrator import (  # noqa: F401
        configure_settings_provider,
        ensure_worker_running,
    )


class TestWakePath:
    """The wake path must actually reach the SDK's ensure_worker_running.

    We reset the module's import-failed flag between tests because
    ``_gpu_import_failed_logged`` is module-level state that persists
    across pytest items.
    """

    def setup_method(self):
        import app.sqs_producer as m
        m._gpu_settings_configured = False
        m._gpu_import_failed_logged = False

    @patch("heimdex_worker_sdk.gpu_orchestrator.ensure_worker_running")
    @patch("heimdex_worker_sdk.gpu_orchestrator.configure_settings_provider")
    def test_fast_path_dispatches_to_sdk(self, mock_configure, mock_ensure):
        """Happy path — import succeeds, ``ensure_worker_running`` is
        called with the job type."""
        from app.sqs_producer import _wake_gpu_worker

        _wake_gpu_worker("blur")

        mock_configure.assert_called_once()
        mock_ensure.assert_called_once_with("blur")

    @patch("heimdex_worker_sdk.gpu_orchestrator.ensure_worker_running")
    @patch("heimdex_worker_sdk.gpu_orchestrator.configure_settings_provider")
    def test_configure_only_called_once(self, mock_configure, mock_ensure):
        """The module-level ``_gpu_settings_configured`` flag must
        prevent re-configuring on every call — otherwise the SDK's
        singleton-lock gets hit for every single SQS publish."""
        from app.sqs_producer import _wake_gpu_worker

        _wake_gpu_worker("blur")
        _wake_gpu_worker("blur")
        _wake_gpu_worker("face")

        # configure only once across 3 publishes
        mock_configure.assert_called_once()
        # ensure called once per publish
        assert mock_ensure.call_count == 3

    @patch("heimdex_worker_sdk.gpu_orchestrator.ensure_worker_running",
           side_effect=RuntimeError("simulated Aircloud outage"))
    @patch("heimdex_worker_sdk.gpu_orchestrator.configure_settings_provider")
    def test_non_import_errors_are_swallowed(self, mock_configure, mock_ensure, caplog):
        """A real Aircloud / network failure must NOT bubble up — the
        user's POST already succeeded before we got here. We just log
        via ``logger.exception`` and move on."""
        import logging
        caplog.set_level(logging.ERROR, logger="app.sqs_producer")

        from app.sqs_producer import _wake_gpu_worker

        # Must not raise
        _wake_gpu_worker("blur")

        # And we logged it instead of eating it silently
        assert any(
            "gpu_orchestrator_wake_failed" in r.getMessage()
            for r in caplog.records
        )

    def test_import_error_logs_once_and_noop(self, monkeypatch, caplog):
        """Simulate the historic regression: heimdex_worker_sdk removed
        from sys.modules and un-importable. The first call must log
        ``gpu_orchestrator_module_unavailable`` at ERROR; subsequent
        calls must stay silent (no log spam) and still not raise."""
        import logging

        # Force the import inside _wake_gpu_worker to fail.
        original_heimdex = {
            k: v for k, v in sys.modules.items()
            if k.startswith("heimdex_worker_sdk")
        }
        for k in list(original_heimdex):
            monkeypatch.delitem(sys.modules, k)
        monkeypatch.setitem(
            sys.modules,
            "heimdex_worker_sdk",
            None,  # None in sys.modules poisons the import
        )

        caplog.set_level(logging.ERROR, logger="app.sqs_producer")

        from app.sqs_producer import _wake_gpu_worker

        # First call — logs at ERROR, no raise
        _wake_gpu_worker("blur")
        first_errors = [
            r for r in caplog.records
            if "gpu_orchestrator_module_unavailable" in r.getMessage()
        ]
        assert len(first_errors) == 1

        # Second + third call — no new ERROR logs, still no raise
        caplog.clear()
        _wake_gpu_worker("blur")
        _wake_gpu_worker("face")
        silent = [
            r for r in caplog.records
            if "gpu_orchestrator_module_unavailable" in r.getMessage()
        ]
        assert silent == []
