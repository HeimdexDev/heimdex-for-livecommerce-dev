"""Search rate-limit tests — per-(org, user) bucket.

Replaces the legacy per-org coverage after 2026-04-24's migration
(``search-rate-limit-per-user`` plan). Biggest behavioral change: two
users in the SAME org are now independent; a user at cap can't starve
their teammates.
"""

from __future__ import annotations

import logging
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.search import rate_limit as rl
from app.modules.search.rate_limit import check_search_rate_limit, reset


@pytest.fixture(autouse=True)
def _clean_buckets():
    reset()
    yield
    reset()


class TestPerUserBucket:
    def test_first_request_allowed(self):
        check_search_rate_limit(uuid4(), uuid4())

    def test_cap_enforced_per_user(self):
        org, user = uuid4(), uuid4()
        # Default cap = 60/60s. Burn them all, then expect 429 on the 61st.
        for _ in range(60):
            check_search_rate_limit(org, user)
        with pytest.raises(HTTPException) as exc:
            check_search_rate_limit(org, user)
        assert exc.value.status_code == 429

    def test_user_isolation_within_same_org(self):
        """Key insight of the migration: User A at cap does NOT affect
        User B in the same org. Previously (per-org) this would 429 B."""
        org = uuid4()
        user_a, user_b = uuid4(), uuid4()
        for _ in range(60):
            check_search_rate_limit(org, user_a)
        # A is at cap
        with pytest.raises(HTTPException):
            check_search_rate_limit(org, user_a)
        # B is unaffected
        check_search_rate_limit(org, user_b)

    def test_same_user_different_orgs_independent(self):
        """Defensive: user_id collision across orgs shouldn't matter
        because the composite key includes org. Unlikely but cheap to
        lock in."""
        user = uuid4()
        org_a, org_b = uuid4(), uuid4()
        for _ in range(60):
            check_search_rate_limit(org_a, user)
        # Same user in different org has a fresh bucket
        check_search_rate_limit(org_b, user)


class TestWindowSlide:
    def test_window_sliding_after_expiry(self):
        """Patch the window to 0 seconds so all prior entries are
        immediately stale on next cleanup — equivalent to waiting the
        full window. More deterministic than time.sleep."""
        org, user = uuid4(), uuid4()
        check_search_rate_limit(org, user)
        # Force the window to 0 so cleanup treats all entries as expired.
        with patch("app.modules.search.rate_limit.get_settings") as mock:
            mock.return_value.search_rate_limit_max_requests = 60
            mock.return_value.search_rate_limit_window_seconds = 0
            # Should be able to do 60 more calls immediately.
            for _ in range(60):
                check_search_rate_limit(org, user)


class TestSettingsDriven:
    def test_custom_cap_from_settings(self):
        org, user = uuid4(), uuid4()
        with patch("app.modules.search.rate_limit.get_settings") as mock:
            mock.return_value.search_rate_limit_max_requests = 5
            mock.return_value.search_rate_limit_window_seconds = 60
            for _ in range(5):
                check_search_rate_limit(org, user)
            with pytest.raises(HTTPException) as exc:
                check_search_rate_limit(org, user)
            assert exc.value.status_code == 429

    def test_custom_window_from_settings(self):
        org, user = uuid4(), uuid4()
        with patch("app.modules.search.rate_limit.get_settings") as mock:
            mock.return_value.search_rate_limit_max_requests = 2
            mock.return_value.search_rate_limit_window_seconds = 7
            check_search_rate_limit(org, user)
            check_search_rate_limit(org, user)
            with pytest.raises(HTTPException) as exc:
                check_search_rate_limit(org, user)
            # Retry-After mirrors the (customized) window
            assert exc.value.headers.get("Retry-After") == "7"


class TestResponseMetadata:
    def test_retry_after_header_present(self):
        org, user = uuid4(), uuid4()
        for _ in range(60):
            check_search_rate_limit(org, user)
        with pytest.raises(HTTPException) as exc:
            check_search_rate_limit(org, user)
        assert exc.value.headers.get("Retry-After") == "60"

    def test_detail_includes_cap_and_window(self):
        org, user = uuid4(), uuid4()
        for _ in range(60):
            check_search_rate_limit(org, user)
        with pytest.raises(HTTPException) as exc:
            check_search_rate_limit(org, user)
        detail = str(exc.value.detail)
        assert "60" in detail  # cap + window both numerically present
        assert "per user" in detail


class TestLogging:
    def test_structured_log_on_429(self):
        """Assert the structured logger fires on 429 with (org_id, user_id).
        Uses the structlog monkey-patch pattern documented in
        .claude/docs/testing.md — caplog doesn't capture structlog
        records directly, so we mock the logger's ``warning`` call."""
        org, user = uuid4(), uuid4()
        for _ in range(60):
            check_search_rate_limit(org, user)
        with patch.object(rl.logger, "warning") as mock_warn:
            with pytest.raises(HTTPException):
                check_search_rate_limit(org, user)
        assert mock_warn.called
        call_kwargs = mock_warn.call_args.kwargs
        assert call_kwargs.get("org_id") == str(org)
        assert call_kwargs.get("user_id") == str(user)
        assert call_kwargs.get("max_requests") == 60
        assert call_kwargs.get("window_seconds") == 60
