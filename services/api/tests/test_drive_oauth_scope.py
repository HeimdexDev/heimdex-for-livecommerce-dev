"""Drive OAuth scope-guard helper coverage.

The 2026-04-27 livenow incident was the result of an OAuth callback
storing a token whose granted scope was ``openid email`` only — Google's
granular consent let the user uncheck ``drive.readonly`` and our code
silently accepted the partial grant. This module asserts the helper
that gates the callback rejects every "missing drive.readonly" shape we
have seen in production.
"""

from __future__ import annotations

import pytest

from app.modules.drive.oauth_router import (
    DRIVE_READONLY_SCOPE,
    _scope_includes_drive_readonly,
)


class TestScopeIncludesDriveReadonly:
    def test_full_scope_with_drive_readonly_passes(self):
        scope = f"openid email {DRIVE_READONLY_SCOPE}"
        assert _scope_includes_drive_readonly(scope) is True

    def test_drive_readonly_in_any_position(self):
        # Order shouldn't matter — Google sometimes reorders scopes
        # in the response.
        assert _scope_includes_drive_readonly(
            f"{DRIVE_READONLY_SCOPE} openid email"
        ) is True
        assert _scope_includes_drive_readonly(
            f"openid {DRIVE_READONLY_SCOPE} email"
        ) is True

    def test_login_only_scope_rejected(self):
        # The exact shape observed in livenow's bad token (2026-04-27).
        scope = "email https://www.googleapis.com/auth/userinfo.email openid"
        assert _scope_includes_drive_readonly(scope) is False

    def test_empty_scope_rejected(self):
        assert _scope_includes_drive_readonly("") is False

    def test_none_scope_rejected(self):
        assert _scope_includes_drive_readonly(None) is False

    def test_drive_file_substring_does_not_pass(self):
        # ``drive.file`` is a different scope (only files the app
        # created/opened); it must not satisfy the readonly check
        # despite sharing a substring.
        assert _scope_includes_drive_readonly(
            "openid email https://www.googleapis.com/auth/drive.file"
        ) is False

    def test_drive_metadata_only_rejected(self):
        # drive.metadata.readonly grants metadata listing but NOT file
        # download — sync needs the full readonly scope.
        assert _scope_includes_drive_readonly(
            "openid email https://www.googleapis.com/auth/drive.metadata.readonly"
        ) is False

    @pytest.mark.parametrize(
        "scope",
        [
            "https://www.googleapis.com/auth/drive",  # full drive read+write — strict subset NOT counted
            "https://www.googleapis.com/auth/drive.readonly.something",
        ],
    )
    def test_other_drive_scopes_rejected(self, scope: str):
        # Conservative: only the exact ``drive.readonly`` URI counts.
        # We could relax this later (``drive`` strictly supersets
        # ``drive.readonly``) but the OAuth flow always asks for
        # ``drive.readonly`` exactly, so anything else is unexpected.
        assert _scope_includes_drive_readonly(scope) is False
