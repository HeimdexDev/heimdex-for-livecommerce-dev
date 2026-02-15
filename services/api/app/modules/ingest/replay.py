import time
from collections import OrderedDict
from threading import Lock

from fastapi import Header, HTTPException, Request, status

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class IdempotencyCache:
    def __init__(self, max_size: int = 10_000):
        self._store: OrderedDict[str, float] = OrderedDict()
        self._lock = Lock()
        self._max_size = max_size

    def check_and_store(self, key: str, ttl: int) -> bool:
        now = time.monotonic()
        with self._lock:
            self._evict_expired(now)
            if key in self._store:
                return False
            if len(self._store) >= self._max_size:
                self._store.popitem(last=False)
            self._store[key] = now + ttl
            return True

    def _evict_expired(self, now: float) -> None:
        while self._store:
            oldest_key, expires_at = next(iter(self._store.items()))
            if expires_at <= now:
                self._store.pop(oldest_key)
            else:
                break


_cache = IdempotencyCache()


def get_idempotency_cache() -> IdempotencyCache:
    return _cache


async def verify_ingest_replay(
    request: Request,
    x_heimdex_timestamp: str | None = Header(None),
    x_heimdex_idempotency_key: str | None = Header(None),
) -> None:
    settings = get_settings()

    if settings.ingest_require_timestamp:
        if not x_heimdex_timestamp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing X-Heimdex-Timestamp header",
            )
        try:
            request_ts = int(x_heimdex_timestamp)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Heimdex-Timestamp must be an integer (unix seconds)",
            ) from None
        server_ts = int(time.time())
        skew = abs(server_ts - request_ts)
        if skew > settings.ingest_timestamp_skew_seconds:
            logger.warning(
                "ingest_timestamp_rejected",
                request_ts=request_ts,
                server_ts=server_ts,
                skew=skew,
                max_skew=settings.ingest_timestamp_skew_seconds,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request timestamp too far from server time (skew={skew}s, max={settings.ingest_timestamp_skew_seconds}s)",
            )

    if settings.ingest_require_idempotency and not x_heimdex_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Heimdex-Idempotency-Key header",
        )

    if x_heimdex_idempotency_key:
        cache = get_idempotency_cache()
        ok = cache.check_and_store(
            x_heimdex_idempotency_key,
            settings.ingest_idempotency_ttl_seconds,
        )
        if not ok:
            logger.warning(
                "ingest_idempotency_replay",
                idempotency_key=x_heimdex_idempotency_key,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate request (idempotency key already used)",
            )
