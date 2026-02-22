from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.ingest.rate_limit import check_ingest_rate_limit, reset


class TestIngestRateLimit:
    def setup_method(self):
        reset()

    def test_allows_under_limit(self):
        for i in range(10):
            check_ingest_rate_limit("192.168.1.1")

    def test_rejects_over_limit(self):
        for i in range(10):
            check_ingest_rate_limit("192.168.1.1")
        with pytest.raises(HTTPException) as exc_info:
            check_ingest_rate_limit("192.168.1.1")
        assert exc_info.value.status_code == 429

    def test_different_ips_independent(self):
        for i in range(10):
            check_ingest_rate_limit("192.168.1.1")
        check_ingest_rate_limit("192.168.1.2")

    def test_reset_clears_state(self):
        for i in range(10):
            check_ingest_rate_limit("192.168.1.1")
        reset()
        check_ingest_rate_limit("192.168.1.1")
