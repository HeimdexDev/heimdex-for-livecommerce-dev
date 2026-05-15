"""Per-user sliding-window rate limit for POST /api/shorts/render.

Mirrors the shape of ``app.modules.search.rate_limit`` but keyed on
``(org_id, user_id)`` instead of just org. Rationale: a single user can
saturate a per-org bucket for the whole team — each render is minutes
long and MBs in size, so even a modest runaway loop burns shared capacity.

In-memory per process. Multiple API workers each hold their own bucket,
so the effective cap is ``N_workers × _MAX_REQUESTS``. Acceptable for v1
(single-container staging + production). Move to Redis if we ever scale
horizontally.
"""

import threading
import time
from collections import defaultdict
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

# 10 submissions per hour per user. Each render is expensive; a power
# user composing 5 variants per hour has headroom, but an automation
# loop submitting every few seconds trips at the 11th request.
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


def check_shorts_render_rate_limit(org_id: UUID, user_id: UUID) -> None:
    """Raise 429 if the (org, user) bucket is already at the cap."""
    key = _bucket_key(org_id, user_id)
    now = time.monotonic()
    with _lock:
        _cleanup_expired(key, now)
        if len(_buckets.get(key, [])) >= _MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Render submission rate limit exceeded "
                    f"({_MAX_REQUESTS}/hour). Try again later."
                ),
            )
        _buckets[key].append(now)


def require_shorts_render_rate_limit(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
) -> None:
    check_shorts_render_rate_limit(org_ctx.org_id, user.id)  # pyright: ignore[reportArgumentType]


def reset() -> None:
    """Test-only: clear all buckets."""
    with _lock:
        _buckets.clear()
