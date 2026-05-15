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
    def test_non_import_errors_are_swallowed(self, mock_configure, mock_ensure):
        """A real Aircloud / network failure must NOT bubble up — the
        user's POST already succeeded before we got here.

        We assert the production contract directly (``_wake_gpu_worker``
        returns normally) instead of checking caplog for the
        ``gpu_orchestrator_wake_failed`` line — ``app.sqs_producer``
        uses ``app.logging_config.get_logger`` which is structlog-bound
        and doesn't propagate to pytest's stdlib-only ``caplog`` fixture.
        The logging call is still exercised (if it raised, this test
        would catch it via the outer no-raise assertion); we just can't
        assert on the record itself without plumbing a structlog
        handler into the test fixture, which is overkill for a
        regression that's already covered by the explicit try/except
        in the source.
        """
        from app.sqs_producer import _wake_gpu_worker

        # Must not raise. If logger.exception itself had a bug, this
        # would surface it.
        _wake_gpu_worker("blur")

        # And the mocked SDK call was actually attempted — proving the
        # error path ran (not a short-circuit on an earlier branch).
        mock_ensure.assert_called_once_with("blur")

    def test_import_error_logs_once_and_noop(self, monkeypatch):
        """Simulate the historic regression: ``heimdex_worker_sdk``
        removed from ``sys.modules`` and un-importable. Three
        production invariants to hold:

          1. None of the calls raise (fire-and-forget contract)
          2. The module-level ``_gpu_import_failed_logged`` flag flips
             to ``True`` on the first call — proving the ImportError
             branch ran
          3. The flag stays ``True`` on subsequent calls — proving the
             log-once short-circuit is working

        We don't assert on caplog records because ``app.sqs_producer``
        uses a structlog-bound logger that doesn't propagate to
        pytest's stdlib-only caplog fixture. The module flag is the
        production contract; caplog was a proxy.
        """
        import app.sqs_producer as m

        # Force the import inside _wake_gpu_worker to fail.
        for k in list(sys.modules):
            if k.startswith("heimdex_worker_sdk"):
                monkeypatch.delitem(sys.modules, k)
        monkeypatch.setitem(
            sys.modules,
            "heimdex_worker_sdk",
            None,  # None in sys.modules poisons the import
        )

        # Precondition: flag is reset by setup_method
        assert m._gpu_import_failed_logged is False

        # First call — flag flips, no raise
        m._wake_gpu_worker("blur")
        assert m._gpu_import_failed_logged is True

        # Subsequent calls — flag stays True, still no raise
        m._wake_gpu_worker("blur")
        m._wake_gpu_worker("face")
        assert m._gpu_import_failed_logged is True
