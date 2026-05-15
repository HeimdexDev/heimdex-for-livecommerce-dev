"""Tests for the subtitle_presets per-(org, user) rate limit."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.subtitle_presets import rate_limit


def setup_function() -> None:
    rate_limit.reset()


def test_under_limit_passes() -> None:
    org = uuid4()
    user = uuid4()
    for _ in range(rate_limit._MAX_REQUESTS):
        rate_limit.check_subtitle_preset_rate_limit(org, user)
    # 30 calls succeed; 31st should raise.


def test_at_limit_raises_429() -> None:
    org = uuid4()
    user = uuid4()
    for _ in range(rate_limit._MAX_REQUESTS):
        rate_limit.check_subtitle_preset_rate_limit(org, user)
    with pytest.raises(HTTPException) as exc:
        rate_limit.check_subtitle_preset_rate_limit(org, user)
    assert exc.value.status_code == 429
    assert exc.value.headers is not None
    assert "Retry-After" in exc.value.headers


def test_buckets_isolated_per_user() -> None:
    org = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    for _ in range(rate_limit._MAX_REQUESTS):
        rate_limit.check_subtitle_preset_rate_limit(org, user_a)
    # user_b is independent — shouldn't be tripped by user_a's calls.
    rate_limit.check_subtitle_preset_rate_limit(org, user_b)


def test_buckets_isolated_per_org() -> None:
    org_a = uuid4()
    org_b = uuid4()
    user = uuid4()
    for _ in range(rate_limit._MAX_REQUESTS):
        rate_limit.check_subtitle_preset_rate_limit(org_a, user)
    # Same user in a different org has its own bucket.
    rate_limit.check_subtitle_preset_rate_limit(org_b, user)
