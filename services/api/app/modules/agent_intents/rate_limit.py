import threading
import time
from collections import defaultdict
from collections.abc import MutableMapping

from fastapi import HTTPException, status

_CREATE_MAX_ATTEMPTS = 10
_CREATE_WINDOW_SECONDS = 600
_create_lock = threading.Lock()
_create_buckets: dict[str, list[float]] = defaultdict(list)

_EXCHANGE_MAX_ATTEMPTS = 5
_EXCHANGE_WINDOW_SECONDS = 600
_exchange_lock = threading.Lock()
_exchange_buckets: dict[str, list[float]] = defaultdict(list)


def _cleanup(
    buckets: MutableMapping[str, list[float]],
    key: str,
    now: float,
    window: int,
) -> None:
    cutoff = now - window
    entries = buckets[key]
    buckets[key] = [t for t in entries if t > cutoff]
    if not buckets[key]:
        del buckets[key]


def check_create_rate_limit(org_id: str) -> None:
    now = time.monotonic()
    with _create_lock:
        _cleanup(_create_buckets, org_id, now, _CREATE_WINDOW_SECONDS)
        if len(_create_buckets.get(org_id, [])) >= _CREATE_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many intent creation attempts. Try again later.",
            )
        _create_buckets[org_id].append(now)


def check_exchange_rate_limit(device_id: str) -> None:
    now = time.monotonic()
    with _exchange_lock:
        _cleanup(_exchange_buckets, device_id, now, _EXCHANGE_WINDOW_SECONDS)
        if len(_exchange_buckets.get(device_id, [])) >= _EXCHANGE_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many intent exchange attempts. Try again later.",
            )
        _exchange_buckets[device_id].append(now)


def reset_create() -> None:
    with _create_lock:
        _create_buckets.clear()


def reset_exchange() -> None:
    with _exchange_lock:
        _exchange_buckets.clear()
