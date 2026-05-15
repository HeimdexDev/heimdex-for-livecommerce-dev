"""Per-(org, user) sliding-window rate limit for POST /api/search*.

Previously keyed on ``org_id`` alone — a livecommerce team of 3-5
concurrent researchers could starve each other out of a single 30/min
bucket. Switched to per-user keying on 2026-04-24 after 156 × 429s in
24h on livenow prod traced back to shared-bucket contention.

In-memory per process. Multiple API workers each hold their own
buckets so the effective cap is ``N_workers × max_requests``. Acceptable
for single-container staging + production. Move to Redis when we scale
horizontally.

Cap + window are driven by settings so ops can raise them temporarily
via env without a redeploy (``SEARCH_RATE_LIMIT_MAX_REQUESTS`` /
``SEARCH_RATE_LIMIT_WINDOW_SECONDS``).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)

_lock = threading.Lock()
_buckets: dict[str, list[float]] = defaultdict(list)


def _bucket_key(org_id: UUID, user_id: UUID) -> str:
    return f"{org_id}:{user_id}"


def _cleanup_expired(key: str, now: float, window_seconds: int) -> None:
    cutoff = now - window_seconds
    entries = _buckets[key]
    _buckets[key] = [t for t in entries if t > cutoff]
    if not _buckets[key]:
        del _buckets[key]


def check_search_rate_limit(org_id: UUID, user_id: UUID) -> None:
    """Raise 429 if the ``(org_id, user_id)`` bucket is at the cap.

    Emits a structured ``search_rate_limit_exceeded`` warning log when
    it fires so ops can ``grep`` for the hot user + their org without
    IP correlation. The 429 response includes a ``Retry-After`` header
    set to the window length so client libraries can back off correctly.
    """
    settings = get_settings()
    max_requests = settings.search_rate_limit_max_requests
    window_seconds = settings.search_rate_limit_window_seconds

    key = _bucket_key(org_id, user_id)
    now = time.monotonic()
    with _lock:
        _cleanup_expired(key, now, window_seconds)
        current = len(_buckets.get(key, []))
        if current >= max_requests:
            logger.warning(
                "search_rate_limit_exceeded",
                org_id=str(org_id),
                user_id=str(user_id),
                current=current,
                max_requests=max_requests,
                window_seconds=window_seconds,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Search rate limit exceeded "
                    f"({max_requests}/{window_seconds}s per user). "
                    f"Try again in a moment."
                ),
                headers={"Retry-After": str(window_seconds)},
            )
        _buckets[key].append(now)


def require_search_rate_limit(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
) -> None:
    check_search_rate_limit(org_ctx.org_id, user.id)  # pyright: ignore[reportArgumentType]


def reset() -> None:
    """Test-only: clear all buckets."""
    with _lock:
        _buckets.clear()
