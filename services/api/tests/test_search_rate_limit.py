import pytest
from fastapi import HTTPException

from app.modules.search.rate_limit import check_search_rate_limit, reset


@pytest.fixture(autouse=True)
def _clean_buckets():
    reset()
    yield
    reset()


class TestSearchRateLimit:
    def test_allows_requests_under_limit(self):
        for _ in range(30):
            check_search_rate_limit("org-1")

    def test_blocks_over_limit(self):
        for _ in range(30):
            check_search_rate_limit("org-2")
        with pytest.raises(HTTPException) as exc_info:
            check_search_rate_limit("org-2")
        assert exc_info.value.status_code == 429

    def test_different_orgs_independent(self):
        for _ in range(30):
            check_search_rate_limit("org-3")
        check_search_rate_limit("org-4")

    def test_window_reset(self):
        import time
        from unittest.mock import patch
        from app.modules.search import rate_limit

        check_search_rate_limit("org-5")

        with patch.object(rate_limit, "_WINDOW_SECONDS", 0):
            time.sleep(0.01)
            for _ in range(30):
                check_search_rate_limit("org-5")
