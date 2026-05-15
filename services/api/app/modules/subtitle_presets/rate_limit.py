"""Per-(org, user) sliding-window rate limit for subtitle preset mutations.

Mirrors ``shorts_render/rate_limit.py``. Mutations only — list and read are
unrestricted (preset listing happens on every editor mount and shouldn't be
gated). Cap is higher than render submissions because presets are cheap.
"""

import threading
import time
from collections import defaultdict
from uuid import UUID

from fastapi import Depends, HTTPException, status

from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

# 30 mutations per hour per user. A user actively editing might save 5-10
# presets in a session; 30 leaves headroom and trips on automation loops.
_MAX_REQUESTS = 30
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


def check_subtitle_preset_rate_limit(org_id: UUID, user_id: UUID) -> None:
    key = _bucket_key(org_id, user_id)
    now = time.monotonic()
    with _lock:
        _cleanup_expired(key, now)
        if len(_buckets.get(key, [])) >= _MAX_REQUESTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Preset mutation rate limit exceeded "
                    f"({_MAX_REQUESTS}/hour). Try again later."
                ),
                headers={"Retry-After": str(_WINDOW_SECONDS)},
            )
        _buckets[key].append(now)


def require_subtitle_preset_rate_limit(
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
) -> None:
    check_subtitle_preset_rate_limit(org_ctx.org_id, user.id)  # pyright: ignore[reportArgumentType]


def reset() -> None:
    """Test-only: clear all buckets."""
    with _lock:
        _buckets.clear()
