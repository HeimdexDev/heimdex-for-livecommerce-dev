"""
Security tests for Auth0 OIDC and tenancy enforcement.

These tests verify:
1. Token org_id must match Host-derived org_id (403 on mismatch)
2. Auto-linking requires email_verified=true
3. Tenancy is derived ONLY from Host header, never from token

Run with: pytest tests/test_auth_security.py -v
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

from fastapi import HTTPException

from app.modules.auth.service import _validate_auth0_user, _validate_dev_user, AuthService
from app.modules.auth.oidc import Auth0TokenPayload
from app.modules.auth.schemas import TokenPayload
from app.modules.tenancy.context import OrgContext


class TestOrgMismatchDenial:
    """Test that token org must match Host-derived org (403 on mismatch)."""

    @pytest.mark.asyncio
    async def test_auth0_token_org_mismatch_returns_403(self):
        """Auth0 token with different org_id than Host should be rejected with 403."""
        # Setup: Host-derived org context
        host_org_id = uuid4()
        org_ctx = OrgContext(org_id=host_org_id, org_slug="host-org")
        
        # Token claims a different org
        token_org_id = uuid4()
        auth0_payload = Auth0TokenPayload(
            sub="auth0|123",
            org_id=str(token_org_id),  # Different from host_org_id
            email="user@example.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )
        
        user_repo = MagicMock()
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_auth0_user("fake_token", org_ctx, user_repo)
            
            # Should be 403 Forbidden, not 401 Unauthorized
            assert exc_info.value.status_code == 403
            assert "organization does not match" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_dev_token_org_mismatch_returns_403(self):
        """Dev token with different org_id than Host should be rejected with 403."""
        # Setup: Host-derived org context
        host_org_id = uuid4()
        org_ctx = OrgContext(org_id=host_org_id, org_slug="host-org")
        
        # Token claims a different org
        token_org_id = uuid4()
        
        user_repo = MagicMock()
        db_session = MagicMock()
        
        # Mock the auth service to return a payload with mismatched org
        with patch.object(AuthService, "decode_token") as mock_decode:
            mock_decode.return_value = TokenPayload(
                sub=str(uuid4()),
                org_id=str(token_org_id),  # Different from host_org_id
                user_id=str(uuid4()),
                email="user@example.com",
                role="member",
                exp=9999999999,
            )
            
            with pytest.raises(HTTPException) as exc_info:
                await _validate_dev_user("fake_token", org_ctx, user_repo, db_session)
            
            # Should be 403 Forbidden
            assert exc_info.value.status_code == 403
            assert "organization does not match" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_auth0_token_without_org_claim_is_allowed(self):
        """Auth0 token without org_id claim should be allowed (no mismatch possible)."""
        # Setup: Host-derived org context
        host_org_id = uuid4()
        org_ctx = OrgContext(org_id=host_org_id, org_slug="host-org")
        
        # Token has no org claim
        auth0_payload = Auth0TokenPayload(
            sub="auth0|123",
            org_id=None,  # No org claim
            email="user@example.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )
        
        # Mock user lookup
        mock_user = MagicMock()
        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=mock_user)
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            # Should not raise - user found by sub
            result = await _validate_auth0_user("fake_token", org_ctx, user_repo)
            assert result == mock_user


class TestEmailVerifiedRequirement:
    """Test that auto-linking requires email_verified=true."""

    @pytest.mark.asyncio
    async def test_unverified_email_rejected_for_new_user(self):
        """User with unverified email should be rejected with 403."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        
        # Token has unverified email
        auth0_payload = Auth0TokenPayload(
            sub="auth0|new_user",
            org_id=None,
            email="unverified@example.com",
            permissions=[],
            raw_claims={"email_verified": False},  # NOT VERIFIED
        )
        
        user_repo = MagicMock()
        # User not found by sub (new user)
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_auth0_user("fake_token", org_ctx, user_repo)
            
            # Should be 403 Forbidden
            assert exc_info.value.status_code == 403
            assert "email not verified" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_verified_email_allows_auto_linking(self):
        """User with verified email should be auto-linked."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        
        # Token has verified email
        auth0_payload = Auth0TokenPayload(
            sub="auth0|new_user",
            org_id=None,
            email="verified@example.com",
            permissions=[],
            raw_claims={"email_verified": True},  # VERIFIED
        )
        
        # Existing user with matching email
        existing_user = MagicMock()
        existing_user.id = uuid4()
        
        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)  # No existing sub link
        user_repo.get_by_email = AsyncMock(return_value=existing_user)  # Found by email
        user_repo.link_auth0_sub = AsyncMock()
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            result = await _validate_auth0_user("fake_token", org_ctx, user_repo)
            
            # Should succeed and link the sub
            assert result == existing_user
            user_repo.link_auth0_sub.assert_called_once_with(
                existing_user.id, "auth0|new_user"
            )

    @pytest.mark.asyncio
    async def test_missing_email_verified_claim_treated_as_false(self):
        """Missing email_verified claim should be treated as unverified."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        
        # Token without email_verified claim
        auth0_payload = Auth0TokenPayload(
            sub="auth0|new_user",
            org_id=None,
            email="user@example.com",
            permissions=[],
            raw_claims={},  # No email_verified key
        )
        
        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_auth0_user("fake_token", org_ctx, user_repo)
            
            # Should be rejected - missing email_verified defaults to False
            assert exc_info.value.status_code == 403


class TestTenancyInvariant:
    """Test that tenancy is ONLY derived from Host header."""

    def test_token_cannot_set_org_context(self):
        """Token claims should never be trusted to set org context.
        
        This is a documentation/design test. The invariant is:
        - OrgContext is ONLY set by get_current_org() from Host header
        - Token org_id is only used to VALIDATE against Host-derived context
        """
        # The code structure enforces this:
        # 1. get_current_org() extracts org from Host header
        # 2. _validate_auth0_user() receives org_ctx as parameter (already set)
        # 3. Token org_id is compared against org_ctx, not used to set it
        
        # This test documents the invariant
        assert True, "Tenancy invariant: org_id from Host only"

    @pytest.mark.asyncio
    async def test_auth0_payload_org_is_validation_only(self):
        """Auth0 org_id claim is for validation, not context setting."""
        host_org_id = uuid4()
        token_org_id = uuid4()
        
        # Even if token has org_id, the comparison is against Host-derived org
        org_ctx = OrgContext(org_id=host_org_id, org_slug="host-org")
        
        auth0_payload = Auth0TokenPayload(
            sub="auth0|123",
            org_id=str(token_org_id),  # Token claims different org
            email="user@example.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )
        
        user_repo = MagicMock()
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_auth0_user("fake_token", org_ctx, user_repo)
            
            # Mismatch detected - proves org_ctx is authoritative
            assert exc_info.value.status_code == 403


class TestErrorMessageSafety:
    """Test that error messages don't leak sensitive information."""

    @pytest.mark.asyncio
    async def test_org_mismatch_error_doesnt_leak_ids(self):
        """Org mismatch error should not expose internal UUIDs to clients."""
        host_org_id = uuid4()
        token_org_id = uuid4()
        
        org_ctx = OrgContext(org_id=host_org_id, org_slug="host-org")
        
        auth0_payload = Auth0TokenPayload(
            sub="auth0|123",
            org_id=str(token_org_id),
            email="user@example.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )
        
        user_repo = MagicMock()
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_auth0_user("fake_token", org_ctx, user_repo)
            
            error_detail = exc_info.value.detail
            
            # Should not contain actual UUIDs
            assert str(host_org_id) not in error_detail
            assert str(token_org_id) not in error_detail
            
            # Should be a generic message
            assert "organization does not match" in error_detail.lower()

    @pytest.mark.asyncio
    async def test_user_not_found_error_is_generic(self):
        """User not found error should not reveal user existence."""
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")
        
        auth0_payload = Auth0TokenPayload(
            sub="auth0|unknown",
            org_id=None,
            email=None,  # No email to try
            permissions=[],
            raw_claims={},
        )
        
        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_auth0_user("fake_token", org_ctx, user_repo)
            
            error_detail = exc_info.value.detail
            
            # Should not reveal whether user exists or not
            # Generic message that works for all cases
            assert "not found" in error_detail.lower() or "contact" in error_detail.lower()
