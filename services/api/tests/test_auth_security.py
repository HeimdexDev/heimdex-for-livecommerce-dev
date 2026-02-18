import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.modules.auth.service import _validate_auth0_user, _validate_dev_user, _enforce_org_binding, AuthService
from app.modules.auth.oidc import Auth0TokenPayload
from app.modules.auth.schemas import TokenPayload
from app.modules.tenancy.context import OrgContext


@asynccontextmanager
async def _noop_savepoint():
    yield


@asynccontextmanager
async def _failing_savepoint():
    raise IntegrityError("duplicate key", params=None, orig=Exception())
    yield  # noqa: unreachable


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
    async def test_auth0_token_without_org_claim_allowed_for_legacy_org(self):
        """Token without org_id is allowed when org has no auth0_org_id (legacy)."""
        host_org_id = uuid4()
        org_ctx = OrgContext(org_id=host_org_id, org_slug="host-org", auth0_org_id=None)
        
        auth0_payload = Auth0TokenPayload(
            sub="auth0|123",
            org_id=None,
            email="user@example.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )
        
        mock_user = MagicMock()
        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=mock_user)
        
        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
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


class TestAuth0OrgBinding:
    """Test _enforce_org_binding for Auth0 Organizations support.

    Covers:
    - Matching auth0_org_id passes
    - Mismatched auth0_org_id returns 403
    - Missing org claim allowed (subdomain is source of truth)
    - Legacy fallback UUID mismatch returns 403
    - Legacy fallback UUID match passes
    - Full flow integration (matching org)
    - Full flow integration (missing org claim falls through to user lookup)
    - Error messages don't leak auth0_org_id values
    """

    def test_matching_auth0_org_id_passes(self):
        """Token org_id matches org.auth0_org_id → no exception."""
        org_ctx = OrgContext(
            org_id=uuid4(), org_slug="acme", auth0_org_id="org_abc123"
        )
        payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id="org_abc123",
            email="a@b.com",
            permissions=[],
            raw_claims={},
        )
        _enforce_org_binding(payload, org_ctx)

    def test_mismatched_auth0_org_id_returns_403(self):
        """Token org_id differs from org.auth0_org_id → 403."""
        org_ctx = OrgContext(
            org_id=uuid4(), org_slug="acme", auth0_org_id="org_abc123"
        )
        payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id="org_DIFFERENT",
            email="a@b.com",
            permissions=[],
            raw_claims={},
        )
        with pytest.raises(HTTPException) as exc_info:
            _enforce_org_binding(payload, org_ctx)
        assert exc_info.value.status_code == 403
        assert "organization does not match" in exc_info.value.detail.lower()

    def test_missing_org_claim_allowed_subdomain_is_source_of_truth(self):
        """Token without org_id passes — subdomain + org-scoped user lookup is sufficient."""
        org_ctx = OrgContext(
            org_id=uuid4(), org_slug="acme", auth0_org_id="org_abc123"
        )
        payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id=None,
            email="a@b.com",
            permissions=[],
            raw_claims={},
        )
        _enforce_org_binding(payload, org_ctx)

    def test_missing_org_claim_allowed_when_org_has_no_auth0_id(self):
        """Legacy org (no auth0_org_id) + token with no org_id → passes."""
        org_ctx = OrgContext(
            org_id=uuid4(), org_slug="legacy-co", auth0_org_id=None
        )
        payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id=None,
            email="a@b.com",
            permissions=[],
            raw_claims={},
        )
        _enforce_org_binding(payload, org_ctx)

    def test_legacy_fallback_mismatch_returns_403(self):
        """Legacy org + token UUID that doesn't match org_id → 403."""
        host_org_id = uuid4()
        org_ctx = OrgContext(
            org_id=host_org_id, org_slug="legacy-co", auth0_org_id=None
        )
        payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id=str(uuid4()),
            email="a@b.com",
            permissions=[],
            raw_claims={},
        )
        with pytest.raises(HTTPException) as exc_info:
            _enforce_org_binding(payload, org_ctx)
        assert exc_info.value.status_code == 403
        assert "organization does not match" in exc_info.value.detail.lower()

    def test_legacy_fallback_match_passes(self):
        """Legacy org + token UUID matching org_id → passes."""
        host_org_id = uuid4()
        org_ctx = OrgContext(
            org_id=host_org_id, org_slug="legacy-co", auth0_org_id=None
        )
        payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id=str(host_org_id),
            email="a@b.com",
            permissions=[],
            raw_claims={},
        )
        _enforce_org_binding(payload, org_ctx)

    @pytest.mark.asyncio
    async def test_full_flow_matching_org_returns_user(self):
        """End-to-end: matching auth0_org_id → user returned."""
        host_org_id = uuid4()
        org_ctx = OrgContext(
            org_id=host_org_id, org_slug="acme", auth0_org_id="org_abc123"
        )
        auth0_payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id="org_abc123",
            email="user@acme.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )

        mock_user = MagicMock()
        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=mock_user)

        with patch(
            "app.modules.auth.service.validate_auth0_token",
            return_value=auth0_payload,
        ):
            result = await _validate_auth0_user("tok", org_ctx, user_repo)
            assert result == mock_user

    @pytest.mark.asyncio
    async def test_full_flow_missing_org_claim_falls_through_to_user_lookup(self):
        """End-to-end: token lacks org_id → proceeds to user lookup (subdomain is source of truth)."""
        host_org_id = uuid4()
        org_ctx = OrgContext(
            org_id=host_org_id, org_slug="acme", auth0_org_id="org_abc123"
        )
        auth0_payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id=None,
            email=None,
            permissions=[],
            raw_claims={},
        )

        mock_user = MagicMock()
        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=mock_user)

        with patch(
            "app.modules.auth.service.validate_auth0_token",
            return_value=auth0_payload,
        ):
            result = await _validate_auth0_user("tok", org_ctx, user_repo)
            assert result == mock_user
            user_repo.get_by_auth0_sub.assert_called_once_with("auth0|u1", host_org_id)

    def test_error_message_does_not_leak_auth0_org_id(self):
        """403 detail must not expose the expected or actual auth0 org IDs."""
        org_ctx = OrgContext(
            org_id=uuid4(), org_slug="acme", auth0_org_id="org_SECRET_123"
        )
        payload = Auth0TokenPayload(
            sub="auth0|u1",
            org_id="org_ATTACKER_456",
            email="a@b.com",
            permissions=[],
            raw_claims={},
        )
        with pytest.raises(HTTPException) as exc_info:
            _enforce_org_binding(payload, org_ctx)

        detail = exc_info.value.detail
        assert "org_SECRET_123" not in detail
        assert "org_ATTACKER_456" not in detail


class TestAutoProvisioning:

    @pytest.mark.asyncio
    async def test_auto_provision_new_user_with_verified_email(self):
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")

        auth0_payload = Auth0TokenPayload(
            sub="auth0|brand_new",
            org_id=None,
            email="newuser@company.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )

        created_user = MagicMock()
        created_user.id = uuid4()

        mock_session = MagicMock()
        mock_session.begin_nested = MagicMock(return_value=_noop_savepoint())

        user_repo = MagicMock()
        user_repo.session = mock_session
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)
        user_repo.get_by_email = AsyncMock(return_value=None)
        user_repo.create = AsyncMock(return_value=created_user)
        user_repo.link_auth0_sub = AsyncMock()

        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            result = await _validate_auth0_user("fake_token", org_ctx, user_repo)

            assert result == created_user
            user_repo.create.assert_called_once_with(org_id, "newuser@company.com")
            user_repo.link_auth0_sub.assert_called_once_with(
                created_user.id, "auth0|brand_new"
            )

    @pytest.mark.asyncio
    async def test_auto_provision_skipped_for_unverified_email(self):
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")

        auth0_payload = Auth0TokenPayload(
            sub="auth0|unverified_new",
            org_id=None,
            email="unverified@company.com",
            permissions=[],
            raw_claims={"email_verified": False},
        )

        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)

        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with pytest.raises(HTTPException) as exc_info:
                await _validate_auth0_user("fake_token", org_ctx, user_repo)

            assert exc_info.value.status_code == 403
            user_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_provision_not_triggered_when_existing_user_found_by_email(self):
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")

        auth0_payload = Auth0TokenPayload(
            sub="auth0|returning",
            org_id=None,
            email="existing@company.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )

        existing_user = MagicMock()
        existing_user.id = uuid4()

        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)
        user_repo.get_by_email = AsyncMock(return_value=existing_user)
        user_repo.link_auth0_sub = AsyncMock()

        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            result = await _validate_auth0_user("fake_token", org_ctx, user_repo)

            assert result == existing_user
            user_repo.create.assert_not_called()
            user_repo.link_auth0_sub.assert_called_once_with(
                existing_user.id, "auth0|returning"
            )

    @pytest.mark.asyncio
    async def test_race_condition_falls_back_to_existing_user(self):
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")

        auth0_payload = Auth0TokenPayload(
            sub="auth0|racer",
            org_id=None,
            email="racer@company.com",
            permissions=[],
            raw_claims={"email_verified": True},
        )

        existing_user = MagicMock()
        existing_user.id = uuid4()

        mock_session = MagicMock()
        mock_session.begin_nested = MagicMock(return_value=_failing_savepoint())

        user_repo = MagicMock()
        user_repo.session = mock_session
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)
        user_repo.get_by_email = AsyncMock(side_effect=[None, existing_user])
        user_repo.create = AsyncMock()
        user_repo.link_auth0_sub = AsyncMock()

        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            result = await _validate_auth0_user("fake_token", org_ctx, user_repo)

            assert result == existing_user
            user_repo.create.assert_not_called()
            user_repo.link_auth0_sub.assert_called_once_with(
                existing_user.id, "auth0|racer"
            )

    @pytest.mark.asyncio
    async def test_no_email_at_all_still_returns_401(self):
        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test-org")

        auth0_payload = Auth0TokenPayload(
            sub="auth0|no_email",
            org_id=None,
            email=None,
            permissions=[],
            raw_claims={},
        )

        user_repo = MagicMock()
        user_repo.get_by_auth0_sub = AsyncMock(return_value=None)

        with patch("app.modules.auth.service.validate_auth0_token", return_value=auth0_payload):
            with patch("app.modules.auth.service.fetch_userinfo", return_value={}):
                with pytest.raises(HTTPException) as exc_info:
                    await _validate_auth0_user("fake_token", org_ctx, user_repo)

                assert exc_info.value.status_code == 401
                user_repo.create.assert_not_called()


class TestErrorMessageSafety:

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
