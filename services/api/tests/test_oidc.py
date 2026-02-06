import pytest
from unittest.mock import patch, MagicMock
import time

from app.modules.auth.oidc import (
    validate_auth0_token,
    _fetch_jwks,
    _get_signing_key,
    clear_jwks_cache,
    Auth0TokenPayload,
    JWKS_CACHE_TTL_SECONDS,
)


class TestJWKSCache:
    @patch("app.modules.auth.oidc.httpx.Client")
    @patch("app.modules.auth.oidc.get_settings")
    def test_fetches_jwks_on_first_call(self, mock_settings, mock_client):
        settings = MagicMock()
        settings.auth0_domain = "test.auth0.com"
        mock_settings.return_value = settings
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "keys": [{"kid": "key1", "kty": "RSA"}]
        }
        mock_client.return_value.__enter__.return_value.get.return_value = mock_response
        
        clear_jwks_cache()
        result = _fetch_jwks()
        
        assert "key1" in result
        assert result["key1"]["kty"] == "RSA"
    
    @patch("app.modules.auth.oidc.httpx.Client")
    @patch("app.modules.auth.oidc.get_settings")
    def test_uses_cache_on_subsequent_calls(self, mock_settings, mock_client):
        settings = MagicMock()
        settings.auth0_domain = "test.auth0.com"
        mock_settings.return_value = settings
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "keys": [{"kid": "key1", "kty": "RSA"}]
        }
        mock_client.return_value.__enter__.return_value.get.return_value = mock_response
        
        clear_jwks_cache()
        _fetch_jwks()
        _fetch_jwks()
        
        assert mock_client.return_value.__enter__.return_value.get.call_count == 1


class TestAuth0TokenValidation:
    @patch("app.modules.auth.oidc.get_settings")
    def test_raises_when_auth0_disabled(self, mock_settings):
        settings = MagicMock()
        settings.auth0_enabled = False
        mock_settings.return_value = settings
        
        with pytest.raises(ValueError, match="Auth0 is not enabled"):
            validate_auth0_token("some_token")
    
    @patch("app.modules.auth.oidc.get_settings")
    def test_raises_when_domain_not_configured(self, mock_settings):
        settings = MagicMock()
        settings.auth0_enabled = True
        settings.auth0_domain = ""
        settings.auth0_audience = "test"
        mock_settings.return_value = settings
        
        with pytest.raises(ValueError, match="domain and audience must be configured"):
            validate_auth0_token("some_token")


class TestAuth0TokenPayload:
    def test_payload_fields(self):
        payload = Auth0TokenPayload(
            sub="auth0|123",
            org_id="org-uuid",
            email="user@example.com",
            permissions=["read:data"],
            raw_claims={"custom": "claim"},
        )
        
        assert payload.sub == "auth0|123"
        assert payload.org_id == "org-uuid"
        assert payload.email == "user@example.com"
        assert payload.permissions == ["read:data"]
        assert payload.raw_claims == {"custom": "claim"}
    
    def test_optional_fields(self):
        payload = Auth0TokenPayload(
            sub="auth0|123",
            org_id=None,
            email=None,
            permissions=[],
            raw_claims={},
        )
        
        assert payload.org_id is None
        assert payload.email is None


class TestClearCache:
    @patch("app.modules.auth.oidc._jwks_cache", None)
    def test_clear_cache_works(self):
        clear_jwks_cache()
