"""Auto-shorts rate limiter is independent of the manual shorts-render bucket."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.shorts_auto.rate_limit import (
    check_auto_shorts_rate_limit,
    reset as reset_auto,
)
from app.modules.shorts_render.rate_limit import (
    check_shorts_render_rate_limit,
    reset as reset_render,
)


@pytest.fixture(autouse=True)
def _reset_buckets():
    reset_auto()
    reset_render()
    yield
    reset_auto()
    reset_render()


class TestRateLimit:
    def test_first_request_allowed(self):
        check_auto_shorts_rate_limit(uuid4(), uuid4())

    def test_blocks_at_default_cap(self):
        org, user = uuid4(), uuid4()
        # Default cap = 10/hour; 11th call must 429.
        for _ in range(10):
            check_auto_shorts_rate_limit(org, user)
        with pytest.raises(HTTPException) as exc:
            check_auto_shorts_rate_limit(org, user)
        assert exc.value.status_code == 429

    def test_per_user_isolation(self):
        org = uuid4()
        u1, u2 = uuid4(), uuid4()
        for _ in range(10):
            check_auto_shorts_rate_limit(org, u1)
        # u2 still has full budget — does not raise
        check_auto_shorts_rate_limit(org, u2)

    def test_independent_of_shorts_render_bucket(self):
        """Burning the auto-shorts bucket must not affect the manual render
        bucket — and vice versa. Different runaway clients can't starve
        each other's budget."""
        org, user = uuid4(), uuid4()
        for _ in range(10):
            check_auto_shorts_rate_limit(org, user)
        # auto bucket is full
        with pytest.raises(HTTPException):
            check_auto_shorts_rate_limit(org, user)
        # render bucket should still have full headroom
        for _ in range(10):
            check_shorts_render_rate_limit(org, user)
        # And vice versa
        reset_auto()
        check_auto_shorts_rate_limit(org, user)
