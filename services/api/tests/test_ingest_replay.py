import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.ingest.replay import IdempotencyCache, verify_ingest_replay


class TestIdempotencyCache:
    def test_first_request_accepted(self):
        cache = IdempotencyCache()
        assert cache.check_and_store("key-1", ttl=60) is True

    def test_duplicate_rejected(self):
        cache = IdempotencyCache()
        cache.check_and_store("key-1", ttl=60)
        assert cache.check_and_store("key-1", ttl=60) is False

    def test_different_keys_accepted(self):
        cache = IdempotencyCache()
        assert cache.check_and_store("key-1", ttl=60) is True
        assert cache.check_and_store("key-2", ttl=60) is True

    def test_eviction_on_max_size(self):
        cache = IdempotencyCache(max_size=2)
        cache.check_and_store("key-1", ttl=60)
        cache.check_and_store("key-2", ttl=60)
        cache.check_and_store("key-3", ttl=60)
        assert cache.check_and_store("key-1", ttl=60) is True


class TestVerifyIngestReplay:
    def _make_settings(self, **overrides):
        s = MagicMock()
        s.ingest_require_timestamp = overrides.get("require_ts", False)
        s.ingest_timestamp_skew_seconds = overrides.get("skew", 300)
        s.ingest_require_idempotency = overrides.get("require_idem", False)
        s.ingest_idempotency_ttl_seconds = overrides.get("idem_ttl", 600)
        return s

    @pytest.mark.asyncio
    async def test_timestamp_valid(self):
        settings = self._make_settings(require_ts=True, skew=300)
        ts = str(int(time.time()))
        request = MagicMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            await verify_ingest_replay(request, x_heimdex_timestamp=ts, x_heimdex_idempotency_key=None)

    @pytest.mark.asyncio
    async def test_timestamp_missing_when_required(self):
        settings = self._make_settings(require_ts=True)
        request = MagicMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(request, x_heimdex_timestamp=None, x_heimdex_idempotency_key=None)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_timestamp_too_old(self):
        settings = self._make_settings(require_ts=True, skew=300)
        ts = str(int(time.time()) - 600)
        request = MagicMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(request, x_heimdex_timestamp=ts, x_heimdex_idempotency_key=None)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_timestamp_not_required_allows_missing(self):
        settings = self._make_settings(require_ts=False)
        request = MagicMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            await verify_ingest_replay(request, x_heimdex_timestamp=None, x_heimdex_idempotency_key=None)

    @pytest.mark.asyncio
    async def test_idempotency_replay_rejected(self):
        settings = self._make_settings(require_idem=False, idem_ttl=600)
        request = MagicMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings), patch(
            "app.modules.ingest.replay.get_idempotency_cache"
        ) as mock_cache:
            cache = IdempotencyCache()
            cache.check_and_store("dup-key", ttl=600)
            mock_cache.return_value = cache
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(
                    request,
                    x_heimdex_timestamp=None,
                    x_heimdex_idempotency_key="dup-key",
                )
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_idempotency_missing_when_required(self):
        settings = self._make_settings(require_idem=True)
        request = MagicMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(request, x_heimdex_timestamp=None, x_heimdex_idempotency_key=None)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_timestamp_non_integer_rejected(self):
        settings = self._make_settings(require_ts=True)
        request = MagicMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(
                    request,
                    x_heimdex_timestamp="not-a-number",
                    x_heimdex_idempotency_key=None,
                )
            assert exc_info.value.status_code == 400
