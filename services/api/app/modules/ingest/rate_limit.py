import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

_MAX_REQUESTS = 10
_WINDOW_SECONDS = 60
_lock = threading.Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _cleanup_expired(key: str, now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    entries = _buckets[key]
    _buckets[key] = [t for t in entries if t > cutoff]
    if not _buckets[key]:
        del _buckets[key]


def check_ingest_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    with _lock:
        _cleanup_expired(client_ip, now)
        if len(_buckets.get(client_ip, [])) >= _MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Ingest rate limit exceeded. Try again later.",
            )
        _buckets[client_ip].append(now)


async def require_ingest_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    check_ingest_rate_limit(client_ip)


def reset() -> None:
    with _lock:
        _buckets.clear()
