import threading
import time
from collections import defaultdict

from fastapi import Depends, HTTPException, status

from app.modules.tenancy import OrgContext, get_current_org

_MAX_REQUESTS = 30
_WINDOW_SECONDS = 60
_lock = threading.Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _cleanup_expired(key: str, now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    entries = _buckets[key]
    _buckets[key] = [t for t in entries if t > cutoff]
    if not _buckets[key]:
        del _buckets[key]


def check_search_rate_limit(org_id: str) -> None:
    now = time.monotonic()
    with _lock:
        _cleanup_expired(org_id, now)
        if len(_buckets.get(org_id, [])) >= _MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Search rate limit exceeded. Try again later.",
            )
        _buckets[org_id].append(now)


async def require_search_rate_limit(
    org_ctx: OrgContext = Depends(get_current_org),
) -> None:
    check_search_rate_limit(str(org_ctx.org_id))


def reset() -> None:
    with _lock:
        _buckets.clear()
