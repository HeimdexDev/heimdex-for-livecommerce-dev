import pytest
from app.modules.tenancy.middleware import extract_org_slug, TenancyError, TenancyMiddleware


class TestExtractOrgSlug:
    """Test org slug extraction from Host header."""
    
    def test_valid_subdomain_local(self):
        slug, error = extract_org_slug("devorg.app.heimdex.local")
        assert slug == "devorg"
        assert error is None
    
    def test_valid_subdomain_production(self):
        slug, error = extract_org_slug("mycompany.app.heimdex.co")
        assert slug == "mycompany"
        assert error is None
    
    def test_subdomain_with_hyphens(self):
        slug, error = extract_org_slug("my-company.app.heimdex.local")
        assert slug == "my-company"
        assert error is None
    
    def test_subdomain_with_numbers(self):
        slug, error = extract_org_slug("org123.app.heimdex.local")
        assert slug == "org123"
        assert error is None
    
    def test_case_insensitive(self):
        slug, error = extract_org_slug("DevOrg.APP.HEIMDEX.LOCAL")
        assert slug == "devorg"
        assert error is None
    
    def test_with_port_number(self):
        slug, error = extract_org_slug("devorg.app.heimdex.local:8000")
        assert slug == "devorg"
        assert error is None
    
    def test_valid_subdomain_staging(self):
        slug, error = extract_org_slug("devorg.app.heimdexdemo.dev")
        assert slug == "devorg"
        assert error is None
    
    def test_staging_with_hyphens(self):
        slug, error = extract_org_slug("my-company.app.heimdexdemo.dev")
        assert slug == "my-company"
        assert error is None
    
    def test_staging_with_port(self):
        slug, error = extract_org_slug("devorg.app.heimdexdemo.dev:443")
        assert slug == "devorg"
        assert error is None
    
    def test_staging_case_insensitive(self):
        slug, error = extract_org_slug("DevOrg.APP.HEIMDEXDEMO.DEV")
        assert slug == "devorg"
        assert error is None


class TestExtractOrgSlugRejections:
    """Test that invalid Host headers are correctly rejected."""
    
    def test_localhost_rejected(self):
        slug, error = extract_org_slug("localhost")
        assert slug is None
        assert error == TenancyError.LOCALHOST
    
    def test_localhost_with_port_rejected(self):
        slug, error = extract_org_slug("localhost:8000")
        assert slug is None
        assert error == TenancyError.LOCALHOST
    
    def test_localhost_with_high_port_rejected(self):
        slug, error = extract_org_slug("localhost:3000")
        assert slug is None
        assert error == TenancyError.LOCALHOST
    
    def test_missing_subdomain_rejected(self):
        slug, error = extract_org_slug("app.heimdex.local")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN
    
    def test_just_domain_rejected(self):
        slug, error = extract_org_slug("heimdex.local")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN
    
    def test_invalid_domain_rejected(self):
        slug, error = extract_org_slug("example.com")
        assert slug is None
        assert error == TenancyError.INVALID_FORMAT
    
    def test_ip_address_rejected(self):
        slug, error = extract_org_slug("127.0.0.1")
        assert slug is None
        assert error == TenancyError.INVALID_FORMAT
    
    def test_ip_with_port_rejected(self):
        slug, error = extract_org_slug("127.0.0.1:8000")
        assert slug is None
        assert error == TenancyError.INVALID_FORMAT
    
    def test_single_char_slug_rejected(self):
        slug, error = extract_org_slug("a.app.heimdex.local")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN
    
    def test_empty_host_rejected(self):
        slug, error = extract_org_slug("")
        assert slug is None
        assert error == TenancyError.INVALID_FORMAT
    
    def test_random_domain_rejected(self):
        slug, error = extract_org_slug("some.random.domain.com")
        assert slug is None
        assert error == TenancyError.INVALID_FORMAT
    
    def test_staging_missing_subdomain_rejected(self):
        slug, error = extract_org_slug("app.heimdexdemo.dev")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN
    
    def test_staging_bare_domain_rejected(self):
        slug, error = extract_org_slug("heimdexdemo.dev")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN
    
    def test_heimdex_dev_not_accepted(self):
        """heimdex.dev is NOT a valid domain — only heimdexdemo.dev is."""
        slug, error = extract_org_slug("devorg.app.heimdex.dev")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN
    
    def test_heimdexdemo_local_not_accepted(self):
        """heimdexdemo.local is NOT valid — only heimdex.local is for dev."""
        slug, error = extract_org_slug("devorg.app.heimdexdemo.local")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN
    
    def test_staging_single_char_slug_rejected(self):
        slug, error = extract_org_slug("a.app.heimdexdemo.dev")
        assert slug is None
        assert error == TenancyError.MISSING_SUBDOMAIN


class TestTenancyErrorMessages:
    """Test that error codes have corresponding messages."""
    
    def test_all_error_codes_have_messages(self):
        from app.modules.tenancy.middleware import ERROR_MESSAGES
        
        assert TenancyError.LOCALHOST in ERROR_MESSAGES
        assert TenancyError.INVALID_FORMAT in ERROR_MESSAGES
        assert TenancyError.MISSING_SUBDOMAIN in ERROR_MESSAGES
    
    def test_localhost_message_mentions_hosts_file(self):
        from app.modules.tenancy.middleware import ERROR_MESSAGES
        
        msg = ERROR_MESSAGES[TenancyError.LOCALHOST]
        assert "/etc/hosts" in msg
        assert "localhost" in msg


class TestTenancyMiddlewareSkipPaths:
    """Test that TenancyMiddleware skips tenancy checks for internal and health paths."""

    @pytest.fixture()
    def captured_state(self):
        """Fixture to capture ASGI scope state after middleware runs."""
        captured = {}

        async def app(scope, receive, send):
            captured.update(scope.get("state", {}))

        return captured, app

    def _make_scope(self, path: str, host: str = "api:8000") -> dict:
        return {
            "type": "http",
            "path": path,
            "headers": [(b"host", host.encode())],
        }

    @pytest.mark.asyncio
    async def test_internal_path_skips_tenancy(self, captured_state):
        captured, app = captured_state
        mw = TenancyMiddleware(app)
        scope = self._make_scope("/internal/drive/jobs/claim")
        await mw(scope, None, None)
        # Internal paths skip tenancy entirely — no org_slug or tenancy_error set
        assert "org_slug" not in captured
        assert "tenancy_error" not in captured

    @pytest.mark.asyncio
    async def test_internal_ingest_path_skips_tenancy(self, captured_state):
        captured, app = captured_state
        mw = TenancyMiddleware(app)
        scope = self._make_scope("/internal/ingest/scenes")
        await mw(scope, None, None)
        assert "org_slug" not in captured

    @pytest.mark.asyncio
    async def test_internal_processing_path_skips_tenancy(self, captured_state):
        captured, app = captured_state
        mw = TenancyMiddleware(app)
        scope = self._make_scope("/internal/drive/processing/claim")
        await mw(scope, None, None)
        assert "org_slug" not in captured

    @pytest.mark.asyncio
    async def test_health_path_skips_tenancy(self, captured_state):
        captured, app = captured_state
        mw = TenancyMiddleware(app)
        scope = self._make_scope("/health")
        await mw(scope, None, None)
        assert "org_slug" not in captured

    @pytest.mark.asyncio
    async def test_api_path_still_runs_tenancy(self, captured_state):
        captured, app = captured_state
        mw = TenancyMiddleware(app)
        scope = self._make_scope("/api/people", host="devorg.app.heimdexdemo.dev")
        await mw(scope, None, None)
        assert captured["org_slug"] == "devorg"
        assert captured["tenancy_error"] is None

    @pytest.mark.asyncio
    async def test_api_path_with_internal_host_logs_error(self, captured_state):
        captured, app = captured_state
        mw = TenancyMiddleware(app)
        scope = self._make_scope("/api/people", host="api:8000")
        await mw(scope, None, None)
        # Non-internal paths with invalid host still get tenancy error
        assert captured["org_slug"] is None
        assert captured["tenancy_error"] == TenancyError.INVALID_FORMAT