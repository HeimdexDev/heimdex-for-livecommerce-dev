"""Deterministic 0-99 rollout bucketing.

Single canonical helper for "is this caller in the X% rollout?".

Consolidation note (2026-05-06): the `_hash_bucket` function in
``app/modules/shorts_auto/scorers/factory.py:50`` predates this
module. Whisper subtitle refinement is the second consumer; that
factory is the first. PR 4 ships this lib for the new code path
without refactoring the factory; the factory should adopt this
import in a follow-up to remove the duplication.

Pure function. No I/O. Trivially testable.
"""

from __future__ import annotations

import hashlib


def hash_bucket(key: str) -> int:
    """Return a deterministic 0-99 bucket from an arbitrary string.

    SHA-1 → first 4 bytes → big-endian int → ``% 100``. Same hash
    function the auto-shorts LLM scorer uses, so a single ``org_id``
    falls into the same bucket across both rollouts. That's
    coincidental, not a guarantee — feature owners pick which key
    to hash on (org_id, video_id, user_id, or a composite).
    """
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 100


def is_in_rollout(*, key: str, rollout_pct: int) -> bool:
    """Whether ``key`` falls inside the active rollout percentage.

    - ``rollout_pct <= 0`` → always ``False`` (kill switch).
    - ``rollout_pct >= 100`` → always ``True`` (full rollout).
    - Otherwise: ``hash_bucket(key) < rollout_pct``.

    Note ``key`` is hashed once per call. For a per-request hot path
    (e.g. inside a tight loop), cache the result against the key
    on the caller side.
    """
    if rollout_pct <= 0:
        return False
    if rollout_pct >= 100:
        return True
    return hash_bucket(key) < rollout_pct
