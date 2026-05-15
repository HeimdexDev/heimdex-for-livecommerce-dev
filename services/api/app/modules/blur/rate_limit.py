"""Per-user sliding-window rate limit for POST /api/videos/{id}/blur.

Mirrors ``app.modules.shorts_render.rate_limit`` but cheaper bucket
(blur is billed per Aircloud GPU minute). If a user clicks
``blur`` on the 11th distinct video in an hour, trip the cap.
"""

import threading
import time
from collections import defaultdict
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

_MAX_REQUESTS = 10
_WINDOW_SECONDS = 60 * 60  # 1 hour

_lock = threading.Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _bucket_key(org_id: UUID, user_id: UUID) -> str:
    return f"{org_id}:{user_id}"


def _cleanup_expired(key: str, now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    entries = _buckets[key]
    _buckets[key] = [t for t in entries if t > cutoff]
    if not _buckets[key]:
        del _buckets[key]


def check_blur_rate_limit(org_id: UUID, user_id: UUID) -> None:
    key = _bucket_key(org_id, user_id)
    now = time.monotonic()
    with _lock:
        _cleanup_expired(key, now)
        if len(_buckets.get(key, [])) >= _MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Blur submission rate limit exceeded "
                    f"({_MAX_REQUESTS}/hour). Try again later."
                ),
            )
        _buckets[key].append(now)


def require_blur_rate_limit(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
) -> None:
    check_blur_rate_limit(org_ctx.org_id, user.id)  # pyright: ignore[reportArgumentType]


def reset() -> None:
    with _lock:
        _buckets.clear()
