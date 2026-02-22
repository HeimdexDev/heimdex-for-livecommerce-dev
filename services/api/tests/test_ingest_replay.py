import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.ingest.replay import (
    check_idempotency_key,
    cleanup_expired_keys,
    verify_ingest_replay,
)


class TestCheckIdempotencyKey:
    @pytest.mark.asyncio
    async def test_first_request_accepted(self):
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        db.execute.return_value = result
        assert await check_idempotency_key(db, "key-1", ttl_seconds=60) is True

    @pytest.mark.asyncio
    async def test_duplicate_rejected(self):
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 0
        db.execute.return_value = result
        assert await check_idempotency_key(db, "key-1", ttl_seconds=60) is False

    @pytest.mark.asyncio
    async def test_different_keys_accepted(self):
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        db.execute.return_value = result
        assert await check_idempotency_key(db, "key-1", ttl_seconds=60) is True
        assert await check_idempotency_key(db, "key-2", ttl_seconds=60) is True

    @pytest.mark.asyncio
    async def test_passes_correct_params(self):
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        db.execute.return_value = result
        await check_idempotency_key(db, "test-key", ttl_seconds=300)
        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["key"] == "test-key"
        assert isinstance(params["expires_at"], datetime)


class TestCleanupExpiredKeys:
    @pytest.mark.asyncio
    async def test_cleanup_returns_rowcount(self):
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 5
        db.execute.return_value = result
        count = await cleanup_expired_keys(db)
        assert count == 5


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
        db = AsyncMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            await verify_ingest_replay(
                request, x_heimdex_timestamp=ts, x_heimdex_idempotency_key=None, db=db,
            )

    @pytest.mark.asyncio
    async def test_timestamp_missing_when_required(self):
        settings = self._make_settings(require_ts=True)
        request = MagicMock()
        db = AsyncMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(
                    request, x_heimdex_timestamp=None, x_heimdex_idempotency_key=None, db=db,
                )
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_timestamp_too_old(self):
        settings = self._make_settings(require_ts=True, skew=300)
        ts = str(int(time.time()) - 600)
        request = MagicMock()
        db = AsyncMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(
                    request, x_heimdex_timestamp=ts, x_heimdex_idempotency_key=None, db=db,
                )
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_timestamp_not_required_allows_missing(self):
        settings = self._make_settings(require_ts=False)
        request = MagicMock()
        db = AsyncMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            await verify_ingest_replay(
                request, x_heimdex_timestamp=None, x_heimdex_idempotency_key=None, db=db,
            )

    @pytest.mark.asyncio
    async def test_idempotency_replay_rejected(self):
        settings = self._make_settings(require_idem=False, idem_ttl=600)
        request = MagicMock()
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 0
        db.execute.return_value = result
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(
                    request,
                    x_heimdex_timestamp=None,
                    x_heimdex_idempotency_key="dup-key",
                    db=db,
                )
            assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_idempotency_new_key_accepted(self):
        settings = self._make_settings(require_idem=False, idem_ttl=600)
        request = MagicMock()
        db = AsyncMock()
        result = MagicMock()
        result.rowcount = 1
        db.execute.return_value = result
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            await verify_ingest_replay(
                request,
                x_heimdex_timestamp=None,
                x_heimdex_idempotency_key="new-key",
                db=db,
            )

    @pytest.mark.asyncio
    async def test_idempotency_missing_when_required(self):
        settings = self._make_settings(require_idem=True)
        request = MagicMock()
        db = AsyncMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(
                    request, x_heimdex_timestamp=None, x_heimdex_idempotency_key=None, db=db,
                )
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_timestamp_non_integer_rejected(self):
        settings = self._make_settings(require_ts=True)
        request = MagicMock()
        db = AsyncMock()
        with patch("app.modules.ingest.replay.get_settings", return_value=settings):
            with pytest.raises(HTTPException) as exc_info:
                await verify_ingest_replay(
                    request,
                    x_heimdex_timestamp="not-a-number",
                    x_heimdex_idempotency_key=None,
                    db=db,
                )
            assert exc_info.value.status_code == 400
