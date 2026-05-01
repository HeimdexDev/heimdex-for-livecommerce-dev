"""Unit tests for the shared internal-auth helpers.

Covers ``app.lib.internal_auth``:
* Pattern B helper ``resolve_resource_with_org`` (Phase 1+2)
* Per-service token helper ``verify_service_identity`` (Phase 3)
* Internal map parser ``_parse_service_tokens``

Each module's internal_router has its own integration tests; this
file pins the helper contracts so the no-info-leak behaviors
(mismatch returns 404, malformed tokens are dropped not crashed,
constant-time compare on bearer) can't regress during refactors.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.lib.internal_auth import (
    _get_service_tokens,
    _parse_service_tokens,
    resolve_resource_with_org,
    verify_service_identity,
)


@dataclass
class _FakeResource:
    """Minimal stand-in for a repo row — only ``org_id`` matters."""
    id: UUID
    org_id: UUID


def _make_lookup(resource: _FakeResource | None):
    """Build an async lookup_fn that returns the given resource."""
    async def _lookup(resource_id: UUID):
        return resource
    return _lookup


# ---------- happy paths ----------


@pytest.mark.asyncio
async def test_returns_resource_and_org_when_header_omitted():
    resource_id = uuid4()
    org_id = uuid4()
    resource = _FakeResource(id=resource_id, org_id=org_id)

    out, derived_org = await resolve_resource_with_org(
        resource_id=resource_id,
        x_heimdex_org_id=None,
        lookup_fn=_make_lookup(resource),
    )
    assert out is resource
    assert derived_org == org_id


@pytest.mark.asyncio
async def test_returns_resource_and_org_when_header_matches():
    resource_id = uuid4()
    org_id = uuid4()
    resource = _FakeResource(id=resource_id, org_id=org_id)

    out, derived_org = await resolve_resource_with_org(
        resource_id=resource_id,
        x_heimdex_org_id=str(org_id),  # matches resource
        lookup_fn=_make_lookup(resource),
    )
    assert out is resource
    assert derived_org == org_id


# ---------- 404s ----------


@pytest.mark.asyncio
async def test_404_when_lookup_returns_none():
    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id=None,
            lookup_fn=_make_lookup(None),
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_404_when_header_mismatches_resource_org():
    """Cross-validation: caller asserts an org that doesn't match
    the resource's org. Response MUST be 404 (not 403, not 422) so
    timing doesn't leak the resource's true tenant."""
    resource_id = uuid4()
    resource_org = uuid4()
    asserted_org = uuid4()
    resource = _FakeResource(id=resource_id, org_id=resource_org)

    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=resource_id,
            x_heimdex_org_id=str(asserted_org),
            lookup_fn=_make_lookup(resource),
        )
    assert excinfo.value.status_code == 404
    # PINNED — flipping this to 403/422 reintroduces the timing leak.
    # Codex F1 fix.
    assert excinfo.value.status_code != 403


@pytest.mark.asyncio
async def test_uses_custom_not_found_detail():
    """Module-specific error text must reach the response so
    operators can distinguish ``channel not found`` from
    ``video not found`` in logs."""
    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id=None,
            lookup_fn=_make_lookup(None),
            not_found_detail="channel not found",
        )
    assert excinfo.value.detail == "channel not found"


# ---------- 400 on malformed header ----------


@pytest.mark.asyncio
async def test_400_when_header_is_not_a_valid_uuid():
    """Header was sent but is malformed (e.g., 'not-a-uuid'). 400
    is correct — this is a client error, distinct from cross-tenant
    mismatch (which is 404). The two error codes intentionally
    diverge."""
    with pytest.raises(HTTPException) as excinfo:
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id="not-a-uuid",
            lookup_fn=_make_lookup(_FakeResource(id=uuid4(), org_id=uuid4())),
        )
    assert excinfo.value.status_code == 400
    assert "X-Heimdex-Org-Id" in excinfo.value.detail


# ---------- helper does not call lookup if header malformed ----------


@pytest.mark.asyncio
async def test_helper_short_circuits_on_malformed_header_before_lookup():
    """A malformed header should fail with 400 before the lookup
    even runs — saves a DB hit on every garbage request."""
    lookup_called = {"yes": False}

    async def _lookup(_id):
        lookup_called["yes"] = True
        return _FakeResource(id=uuid4(), org_id=uuid4())

    with pytest.raises(HTTPException):
        await resolve_resource_with_org(
            resource_id=uuid4(),
            x_heimdex_org_id="garbage",
            lookup_fn=_lookup,
        )
    assert lookup_called["yes"] is False


# =====================================================================
# F1 Phase 3 — _parse_service_tokens
# =====================================================================


def test_parse_service_tokens_empty_returns_empty_dict():
    assert _parse_service_tokens("") == {}


def test_parse_service_tokens_single_entry():
    assert _parse_service_tokens("drive-worker:abc123") == {"drive-worker": "abc123"}


def test_parse_service_tokens_multiple_entries():
    raw = "drive-worker:tok1,blur-worker:tok2,worker-events:tok3"
    parsed = _parse_service_tokens(raw)
    assert parsed == {
        "drive-worker": "tok1",
        "blur-worker": "tok2",
        "worker-events": "tok3",
    }


def test_parse_service_tokens_trims_whitespace():
    raw = "  drive-worker : tok1 ,  blur-worker:tok2 "
    assert _parse_service_tokens(raw) == {
        "drive-worker": "tok1",
        "blur-worker": "tok2",
    }


def test_parse_service_tokens_drops_malformed_entries_without_crashing():
    """Defensive parsing: a single typo in env config shouldn't take
    the api offline. Bad entries are logged + dropped; valid ones
    survive."""
    raw = "drive-worker:tok1,malformed-no-colon,blur-worker:tok2,:no-id-token,nokey:"
    assert _parse_service_tokens(raw) == {
        "drive-worker": "tok1",
        "blur-worker": "tok2",
    }


def test_parse_service_tokens_handles_token_containing_colons():
    """Token contains the bearer prefix or other colons. ``partition``
    splits on first colon only, preserving the rest of the token."""
    raw = "drive-worker:Bearer:something:complex"
    assert _parse_service_tokens(raw) == {
        "drive-worker": "Bearer:something:complex",
    }


# =====================================================================
# F1 Phase 3 — verify_service_identity
# =====================================================================


def _patch_settings(monkeypatch, *, internal_service_tokens: str = "", drive_internal_api_key: str = ""):
    """Override the cached settings + parsed tokens for one test."""
    from app.config import get_settings
    from app.lib import internal_auth as auth_module
    from types import SimpleNamespace

    fake_settings = SimpleNamespace(
        internal_service_tokens=internal_service_tokens,
        drive_internal_api_key=drive_internal_api_key,
    )
    monkeypatch.setattr(auth_module, "_get_service_tokens", lambda: _parse_service_tokens(internal_service_tokens))
    # Patch get_settings via the auth module's import (which is a
    # late import inside the function — must patch app.config).
    import app.config as config_module
    monkeypatch.setattr(config_module, "get_settings", lambda: fake_settings)


@pytest.mark.asyncio
async def test_service_identity_legacy_path_accepts_global_bearer(monkeypatch):
    """Legacy path: no service-id header, bearer matches the legacy
    global key. Returns ``"legacy"`` so endpoint code can log the
    auth path."""
    _patch_settings(monkeypatch, drive_internal_api_key="legacy-secret")

    sid = await verify_service_identity(
        authorization="Bearer legacy-secret",
        x_heimdex_service_id=None,
    )
    assert sid == "legacy"


@pytest.mark.asyncio
async def test_service_identity_legacy_path_rejects_wrong_bearer(monkeypatch):
    _patch_settings(monkeypatch, drive_internal_api_key="legacy-secret")

    with pytest.raises(HTTPException) as exc:
        await verify_service_identity(
            authorization="Bearer wrong",
            x_heimdex_service_id=None,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_service_identity_legacy_path_503_when_unconfigured(monkeypatch):
    """If ``drive_internal_api_key`` is empty AND no service-id is
    sent, the api isn't configured for any auth → 503."""
    _patch_settings(monkeypatch, drive_internal_api_key="")

    with pytest.raises(HTTPException) as exc:
        await verify_service_identity(
            authorization="Bearer anything",
            x_heimdex_service_id=None,
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_service_identity_new_path_accepts_matching_token(monkeypatch):
    """New path: service-id header present, bearer matches the
    per-service token. Returns the verified service_id."""
    _patch_settings(
        monkeypatch,
        internal_service_tokens="drive-worker:tok1,blur-worker:tok2",
        drive_internal_api_key="legacy-secret",
    )

    sid = await verify_service_identity(
        authorization="Bearer tok2",
        x_heimdex_service_id="blur-worker",
    )
    assert sid == "blur-worker"


@pytest.mark.asyncio
async def test_service_identity_new_path_rejects_wrong_token(monkeypatch):
    """Bearer doesn't match the expected token for the asserted
    service_id → 401. Specifically does NOT fall through to the
    legacy bearer — sending a service-id is an explicit choice and
    the api shouldn't silently accept the legacy path as a
    fallback when the token mismatches."""
    _patch_settings(
        monkeypatch,
        internal_service_tokens="drive-worker:tok1",
        drive_internal_api_key="legacy-secret",  # NOT used
    )

    with pytest.raises(HTTPException) as exc:
        await verify_service_identity(
            authorization="Bearer legacy-secret",  # legacy bearer
            x_heimdex_service_id="drive-worker",  # but with service id
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_service_identity_new_path_rejects_unknown_service(monkeypatch):
    """A service-id header that isn't in the tokens map → 401. NOT
    a fall-through to legacy: a misconfigured worker shouldn't
    accidentally pass auth."""
    _patch_settings(
        monkeypatch,
        internal_service_tokens="drive-worker:tok1",
        drive_internal_api_key="legacy-secret",
    )

    with pytest.raises(HTTPException) as exc:
        await verify_service_identity(
            authorization="Bearer tok1",
            x_heimdex_service_id="not-a-registered-service",
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_service_identity_rejects_malformed_authorization_header(monkeypatch):
    _patch_settings(monkeypatch, drive_internal_api_key="legacy-secret")

    for bad in ["", "tok1", "Token tok1", "Bearer", "Basic foo"]:
        with pytest.raises(HTTPException) as exc:
            await verify_service_identity(
                authorization=bad,
                x_heimdex_service_id=None,
            )
        assert exc.value.status_code == 401, f"expected 401 for {bad!r}"


@pytest.mark.asyncio
async def test_service_identity_returns_service_id_not_legacy_for_audit(monkeypatch):
    """Audit invariant: when the new path is used, return the
    actual service_id (not "legacy" / a generic value). Endpoint
    audit logs need this distinction."""
    _patch_settings(
        monkeypatch,
        internal_service_tokens="drive-worker:tok1,blur-worker:tok2,worker-events:tok3",
        drive_internal_api_key="legacy-secret",
    )

    for sid, tok in [
        ("drive-worker", "tok1"),
        ("blur-worker", "tok2"),
        ("worker-events", "tok3"),
    ]:
        result = await verify_service_identity(
            authorization=f"Bearer {tok}",
            x_heimdex_service_id=sid,
        )
        assert result == sid


@pytest.mark.asyncio
async def test_service_identity_constant_time_compare_smoke(monkeypatch):
    """Smoke test the constant-time compare path. Real timing
    measurement is out of scope for unit tests; this just ensures
    we're calling ``hmac.compare_digest`` (passes for matching,
    rejects mismatching)."""
    _patch_settings(monkeypatch, drive_internal_api_key="abcdef")

    assert (
        await verify_service_identity(
            authorization="Bearer abcdef",
            x_heimdex_service_id=None,
        )
        == "legacy"
    )

    # Same length, different value
    with pytest.raises(HTTPException):
        await verify_service_identity(
            authorization="Bearer ABCDEF",
            x_heimdex_service_id=None,
        )
