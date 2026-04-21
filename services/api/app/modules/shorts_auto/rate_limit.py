"""Per-user sliding-window rate limit for /api/shorts/auto-* endpoints.

Independent of ``shorts_render.rate_limit`` so a runaway auto-render
client can't exhaust the manual render budget (or vice versa). Same
in-memory shape as that module — both pre-Redis. Move to Redis if we
ever scale the API horizontally.

Cap is configured via ``Settings.auto_shorts_rate_limit_per_hour``.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.config import get_settings
from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

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


def check_auto_shorts_rate_limit(org_id: UUID, user_id: UUID) -> None:
    """Raise 429 if the (org, user) bucket is at the cap.

    Reads the cap from settings on every call so a config flip takes
    effect without restarting the API.
    """
    settings = get_settings()
    max_requests = settings.auto_shorts_rate_limit_per_hour

    key = _bucket_key(org_id, user_id)
    now = time.monotonic()
    with _lock:
        _cleanup_expired(key, now)
        if len(_buckets.get(key, [])) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Auto-shorts submission rate limit exceeded "
                    f"({max_requests}/hour). Try again later."
                ),
            )
        _buckets[key].append(now)


def require_auto_shorts_rate_limit(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
) -> None:
    check_auto_shorts_rate_limit(org_ctx.org_id, user.id)  # pyright: ignore[reportArgumentType]


def reset() -> None:
    """Test-only: clear all buckets."""
    with _lock:
        _buckets.clear()
