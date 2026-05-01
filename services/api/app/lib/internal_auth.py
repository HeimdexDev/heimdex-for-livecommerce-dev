"""Shared Pattern B internal-auth helper.

Background
----------
The api's internal endpoints have historically authenticated workers
two ways:

* **Pattern A**: shared bearer + caller-asserted ``X-Heimdex-Org-Id``
  header. The repo lookup filters by both ``resource_id`` AND
  ``org_id``. Protects against cross-tenant access only as long as the
  ``(resource_id, org_id)`` pair never leaks together. Fragile.

* **Pattern B**: shared bearer + resource-derived ``org_id``. The
  bearer authenticates the call; the resource's own ``org_id`` is the
  canonical tenant context. Header (when sent) is a soft
  cross-validation that 404s on mismatch. Already in production for
  ``blur/`` + ``shorts_auto_product/`` internal endpoints.

Codex adversarial review F1 (2026-05-01) flagged Pattern A as a real
multi-tenant isolation gap. The fix is migration to Pattern B; this
module centralizes the migration so each module's
``internal_router.py`` is a one-line helper call away from the right
auth flow.

Usage
-----

::

    from app.lib.internal_auth import resolve_resource_with_org

    @router.get("/youtube/channels/{channel_id}/video_ids")
    async def get_known_video_ids(
        channel_id: UUID,
        x_heimdex_org_id: str | None = Header(default=None, alias="X-Heimdex-Org-Id"),
        _token: str = Depends(verify_internal_token),
        db: AsyncSession = Depends(get_db_session),
    ):
        repo = YouTubeChannelRepository(db)
        channel, org_id = await resolve_resource_with_org(
            resource_id=channel_id,
            x_heimdex_org_id=x_heimdex_org_id,
            lookup_fn=repo.get_by_id_resource_scoped,
            not_found_detail="channel not found",
        )
        ...

The repo MUST expose a ``get_by_id_resource_scoped(id)`` method that
looks up by id alone (no org filter) and returns a row with an
``.org_id`` attribute. The corresponding ``get_by_id(id, org_id)``
method (Pattern A) is intentionally NOT touched — Pattern A callers
in non-migrated code keep using it; mixing the two would silently
regress.

Constraints
-----------
- Cross-validation mismatch returns **404** (NOT 400, NOT 403).
  Same response as a true not-found so timing doesn't reveal the
  resource's true tenant. Pinned by tests.
- Helper does NOT verify the bearer — caller's
  ``Depends(verify_internal_token)`` is the bearer gate. Helper only
  enforces tenant binding once the bearer has passed.
- Helper does NOT log on mismatch by default (log spam from
  brute-force probes). Add explicit warning log at the call site if
  the threat model warrants it.
- Header is OPTIONAL (``Header(default=None, ...)``). Workers may
  continue to send it (no worker change required) or omit it; api
  derives org from the resource either way.
- ``not_found_detail`` lets endpoints return module-specific text
  (e.g., "channel not found", "video not found") so the Pattern A
  endpoints' existing error UX doesn't regress.
"""

from __future__ import annotations

import hmac
import logging
from functools import lru_cache
from typing import Any, Awaitable, Callable, TypeVar
from uuid import UUID

from fastapi import Header, HTTPException, status

ResourceIdT = TypeVar("ResourceIdT")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# F1 Phase 3 — per-service tokens
# ---------------------------------------------------------------------------
#
# The internal endpoints WITHOUT a path resource (worker_events POST,
# ingest/scenes POST, ingest/enrich POST) can't use Pattern B because
# there's no resource to derive the org from. The risk: a leaked
# global bearer or compromised worker has the full surface of these
# endpoints, including the ability to fake events / write scenes
# into ANY tenant's index.
#
# Phase 3 mitigates this with **per-service tokens**: each worker
# gets its own token + a service identity. The api validates the
# bearer matches the claimed service. Cross-service blast radius
# from a leaked token is bounded to that service's surface.
#
# Backward-compat is the linchpin: this PR ships the api side only.
# Workers still send the legacy ``drive_internal_api_key`` bearer
# (no worker code change). The new auth dependency falls back to
# the legacy bearer when ``X-Heimdex-Service-Id`` isn't sent. Once
# workers adopt the new header in a follow-up rollout, the legacy
# fallback can be removed.


def _parse_service_tokens(raw: str) -> dict[str, str]:
    """Parse the ``INTERNAL_SERVICE_TOKENS`` env value into a
    ``service_id → token`` map.

    Format: ``service_id:token,service_id:token,...``. Whitespace is
    trimmed. Empty entries are skipped silently. Malformed entries
    (no colon, empty service_id, empty token) are dropped with a
    warning — preferred over a 500 at boot time so a single typo
    doesn't take the api offline.
    """
    if not raw:
        return {}
    out: dict[str, str] = {}
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if ":" not in piece:
            logger.warning(
                "internal_service_tokens_malformed_entry",
                extra={"entry_preview": piece[:20]},
            )
            continue
        sid, _, token = piece.partition(":")
        sid = sid.strip()
        token = token.strip()
        if not sid or not token:
            logger.warning(
                "internal_service_tokens_empty_field",
                extra={"sid_set": bool(sid), "token_set": bool(token)},
            )
            continue
        out[sid] = token
    return out


@lru_cache(maxsize=1)
def _get_service_tokens() -> dict[str, str]:
    """Cached parsed map. Reads ``settings.internal_service_tokens``
    once per process — workers don't change tokens at runtime.
    Tests can clear via ``_get_service_tokens.cache_clear()``.
    """
    from app.config import get_settings
    return _parse_service_tokens(get_settings().internal_service_tokens)


def _check_token_constant_time(provided: str, expected: str) -> bool:
    """Constant-time string compare. Prevents timing-side-channel
    leaks on bearer comparisons."""
    return hmac.compare_digest(provided, expected)


async def verify_service_identity(
    authorization: str = Header(..., alias="Authorization"),
    x_heimdex_service_id: str | None = Header(default=None, alias="X-Heimdex-Service-Id"),
) -> str:
    """Auth dependency for internal endpoints WITHOUT a path resource.

    Returns the verified ``service_id`` string. Endpoints log this
    on every call for audit. Endpoint code never trusts a body- or
    header-asserted service identity for authorization decisions —
    only the value returned here.

    Behavior:

      * **New path** — ``X-Heimdex-Service-Id`` header IS present:
        * Service id MUST be a configured key in
          ``settings.internal_service_tokens``.
        * Bearer MUST match the corresponding token (constant-time).
        * Returns the verified ``service_id``.

      * **Legacy fallback** — ``X-Heimdex-Service-Id`` is absent:
        * Bearer MUST match the legacy ``drive_internal_api_key``.
        * Returns ``"legacy"`` so endpoint code can log the path.

    Either way, a mismatch is **401**. The endpoint never sees an
    unauthenticated request.

    The legacy fallback is intentional: workers ship per-service
    tokens in a follow-up rollout. Until then, the api accepts both
    paths so the same release doesn't require simultaneous worker +
    api updates. Once worker adoption is 100%, remove the fallback
    by setting ``settings.drive_internal_api_key = ""``.
    """
    from app.config import get_settings
    settings = get_settings()

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    provided = parts[1]

    if x_heimdex_service_id is not None:
        # New service-id path. The service must be registered.
        tokens = _get_service_tokens()
        expected = tokens.get(x_heimdex_service_id)
        if expected is None:
            logger.warning(
                "internal_service_unknown",
                extra={"service_id": x_heimdex_service_id},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unknown service",
            )
        if not _check_token_constant_time(provided, expected):
            logger.warning(
                "internal_service_token_mismatch",
                extra={"service_id": x_heimdex_service_id},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token for service",
            )
        return x_heimdex_service_id

    # Legacy fallback. Same behavior as the existing
    # ``verify_internal_token``.
    if not settings.drive_internal_api_key:
        logger.error("drive_internal_api_key_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API not configured",
        )
    if not _check_token_constant_time(provided, settings.drive_internal_api_key):
        logger.warning("internal_auth_invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
        )
    return "legacy"


async def resolve_resource_with_org(
    *,
    resource_id: ResourceIdT,
    x_heimdex_org_id: str | None,
    lookup_fn: Callable[[ResourceIdT], Awaitable[Any]],
    not_found_detail: str = "resource not found",
) -> tuple[Any, UUID]:
    """Resolve a path resource and derive its org context (Pattern B).

    Args:
        resource_id: UUID from the endpoint's path parameter.
        x_heimdex_org_id: Optional ``X-Heimdex-Org-Id`` header value.
            ``None`` when caller omits the header (the new Pattern B
            ideal). String when caller sends it (back-compat path —
            cross-validated against the resource).
        lookup_fn: Async callable taking a UUID and returning either
            ``None`` (not found) or a row with an ``.org_id``
            attribute. The repo's ``get_by_id_resource_scoped`` is
            the canonical input.
        not_found_detail: Detail string for the 404 response. Defaults
            to a generic message; pass an endpoint-specific one to
            preserve existing error UX.

    Returns:
        ``(resource, org_id)`` tuple. ``org_id`` always equals
        ``resource.org_id`` — caller can use either, but using the
        return tuple makes the resource-derived intent explicit at
        the call site.

    Raises:
        HTTPException 400: Header was provided but isn't a valid UUID.
        HTTPException 404: Resource not found, OR header was provided
            and didn't match the resource's ``org_id``. The 404 is
            intentional — same response as not-found so timing
            doesn't reveal the resource's true tenant. NEVER change
            this to 403 or 422.
    """
    asserted_org_id: UUID | None = None
    # Defensive: tests sometimes call endpoint functions directly
    # (no FastAPI in the loop). The default for ``Header(default=None,
    # ...)`` resolves at request time to ``None``, but a direct
    # function call sees the literal ``Header`` marker object as the
    # default. Treat any non-string value as "not provided" — only
    # real strings reach the UUID parse path.
    if isinstance(x_heimdex_org_id, str):
        try:
            asserted_org_id = UUID(x_heimdex_org_id)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
            )

    resource = await lookup_fn(resource_id)
    if resource is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    if asserted_org_id is not None and asserted_org_id != resource.org_id:
        # Cross-tenant access attempt. 404 (NOT 403) so the response
        # is indistinguishable from a genuine not-found — does not
        # confirm whether the resource_id exists in any tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=not_found_detail,
        )

    return resource, resource.org_id
