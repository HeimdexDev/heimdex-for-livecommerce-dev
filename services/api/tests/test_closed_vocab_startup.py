"""
Tests for ``startup_closed_vocab_check`` — the eager-init reachability
probe added to the api lifespan after PR 171 review surfaced the
silent-fail-open pattern (memory: feedback_external_lib_eager_init_fail_loud.md).

Three behaviors locked in:
  * Disabled flag → no-op (no log emitted, no HTTP call)
  * Enabled but empty URL → loud ``closed_vocab_startup_misconfigured`` ERROR
  * Enabled but unreachable → loud ``closed_vocab_startup_unreachable`` ERROR

Does NOT raise in any case — fail-open semantics of ``classify()`` are
preserved at the search-service layer.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from app.modules.search.closed_vocab import startup_closed_vocab_check


def _settings(**overrides):
    base = {
        "closed_vocab_enabled": False,
        "closed_vocab_service_url": "",
        "closed_vocab_timeout_ms": 1000,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_disabled_is_noop():
    """When the flag is off, the probe must not log or open a client."""
    with patch("app.modules.search.closed_vocab.logger") as mock_logger:
        with patch("httpx.AsyncClient") as mock_client:
            await startup_closed_vocab_check(_settings(closed_vocab_enabled=False))
    mock_logger.error.assert_not_called()
    mock_logger.info.assert_not_called()
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_enabled_empty_url_logs_misconfigured():
    """Enabled + empty URL = config bug; surface a loud ERROR."""
    with patch("app.modules.search.closed_vocab.logger") as mock_logger:
        await startup_closed_vocab_check(
            _settings(closed_vocab_enabled=True, closed_vocab_service_url="")
        )
    mock_logger.error.assert_called_once()
    args, kwargs = mock_logger.error.call_args
    assert args[0] == "closed_vocab_startup_misconfigured"


@pytest.mark.asyncio
async def test_enabled_unreachable_logs_unreachable():
    """Enabled + unreachable host = the wedge mode PR 171 is fixing.

    Must log ERROR (not just WARNING) so operators don't have to grep
    per-query logs.
    """
    async def fail(*args, **kwargs):
        raise httpx.ConnectError("Name or service not known")

    with patch("app.modules.search.closed_vocab.logger") as mock_logger:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_instance = mock_client_cls.return_value.__aenter__.return_value
            mock_client_instance.get = fail
            await startup_closed_vocab_check(
                _settings(
                    closed_vocab_enabled=True,
                    closed_vocab_service_url="http://closed-vocab-search:8080",
                )
            )

    mock_logger.error.assert_called_once()
    args, kwargs = mock_logger.error.call_args
    assert args[0] == "closed_vocab_startup_unreachable"
    assert kwargs.get("base_url") == "http://closed-vocab-search:8080"
    assert "Name or service not known" in kwargs.get("error", "")


@pytest.mark.asyncio
async def test_enabled_healthy_logs_info():
    """Enabled + healthy sidecar = quiet success path."""
    class _FakeResponse:
        content = b'{"status":"ok","vocab_size":162}'
        def raise_for_status(self):
            pass
        def json(self):
            return {"status": "ok", "vocab_size": 162}

    async def ok(*args, **kwargs):
        return _FakeResponse()

    with patch("app.modules.search.closed_vocab.logger") as mock_logger:
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client_instance = mock_client_cls.return_value.__aenter__.return_value
            mock_client_instance.get = ok
            await startup_closed_vocab_check(
                _settings(
                    closed_vocab_enabled=True,
                    closed_vocab_service_url="http://closed-vocab-search:8080",
                )
            )

    mock_logger.error.assert_not_called()
    mock_logger.info.assert_called_once()
    args, kwargs = mock_logger.info.call_args
    assert args[0] == "closed_vocab_startup_ok"
    assert kwargs.get("vocab_size") == 162
