import re

import pytest

from app.config import Settings


class TestCORSOriginRegex:
    @pytest.fixture
    def pattern(self):
        settings = Settings()
        return re.compile(settings.cors_allow_origin_regex)

    @pytest.mark.parametrize(
        "origin",
        [
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://devorg.app.heimdex.local:3000",
            "https://devorg.app.heimdex.local:3000",
            "https://myorg.app.heimdex.co",
            "https://myorg.app.heimdex.co:443",
            "http://test-org.app.heimdex.local:8000",
            "https://a1.app.heimdex.co",
            "https://devorg.app.heimdexdemo.dev",
            "http://devorg.app.heimdexdemo.dev:3000",
        ],
    )
    def test_allowed_origins(self, pattern, origin):
        assert pattern.match(origin), f"{origin} should be allowed"

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.com",
            "https://heimdex.co.evil.com",
            "https://evil.app.heimdex.co.evil.com",
            "http://.app.heimdex.local:3000",
            "http://-bad.app.heimdex.local:3000",
            "http://bad-.app.heimdex.local:3000",
            "http://localhost:3000/path",
            "",
            "null",
            "https://app.heimdex.co",
        ],
    )
    def test_rejected_origins(self, pattern, origin):
        assert not pattern.match(origin), f"{origin} should be rejected"

    def test_vary_origin_not_wildcard(self):
        settings = Settings()
        assert settings.cors_allow_origin_regex != ""
        assert "*" not in settings.cors_allow_origin_regex
