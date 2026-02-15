import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 600
_lock = threading.Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _cleanup_expired(ip: str, now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    entries = _buckets[ip]
    _buckets[ip] = [t for t in entries if t > cutoff]
    if not _buckets[ip]:
        del _buckets[ip]


def check_pairing_rate_limit(ip: str) -> None:
    now = time.monotonic()
    with _lock:
        _cleanup_expired(ip, now)
        if len(_buckets.get(ip, [])) >= _MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many pairing attempts. Try again later.",
            )
        _buckets[ip].append(now)


async def require_pairing_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    check_pairing_rate_limit(ip)


def reset() -> None:
    with _lock:
        _buckets.clear()
