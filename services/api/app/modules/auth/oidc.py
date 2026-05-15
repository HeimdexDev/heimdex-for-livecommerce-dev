"""
OIDC token validation service.

Validates JWT access tokens issued by any OIDC provider (Auth0, Keycloak,
Azure AD, etc.) using JWKS (RS256).  Auth0 remains the default for cloud
deployments; on-prem deployments set OIDC_ISSUER to use a generic provider.

Caches JWKS keys to avoid repeated HTTP calls.
"""
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from jose import JWTError, jwt

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

JWKS_CACHE_TTL_SECONDS = 3600
USERINFO_CACHE_TTL_SECONDS = 300

_cache_lock = threading.Lock()


@dataclass
class JWKSCache:
    keys: dict[str, Any]
    fetched_at: float


@dataclass
class _UserinfoEntry:
    data: dict[str, Any]
    fetched_at: float


_jwks_cache: JWKSCache | None = None
_userinfo_cache: dict[str, _UserinfoEntry] = {}
_http_client: httpx.Client | None = None


def _get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=10.0)
    return _http_client


def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        _http_client.close()
        _http_client = None


def _get_jwks_uri() -> str:
    """Resolve JWKS URI from config.

    Priority: OIDC_JWKS_URI > OIDC_ISSUER discovery > Auth0 domain derivation.
    """
    settings = get_settings()

    if settings.oidc_jwks_uri:
        return settings.oidc_jwks_uri

    if settings.oidc_issuer:
        return _discover_jwks_uri(settings.oidc_issuer)

    return f"https://{settings.auth0_domain}/.well-known/jwks.json"


def _get_issuer() -> str:
    """Resolve expected JWT issuer.

    Priority: OIDC_ISSUER > Auth0 domain derivation.
    """
    settings = get_settings()
    if settings.oidc_issuer:
        return settings.oidc_issuer
    return f"https://{settings.auth0_domain}/"


def _get_org_claim() -> str:
    """Resolve the claim name for org_id in JWT payload."""
    settings = get_settings()
    if settings.oidc_org_claim:
        return settings.oidc_org_claim
    return settings.auth0_org_claim


@lru_cache(maxsize=4)
def _discover_jwks_uri(issuer: str) -> str:
    """Discover JWKS URI from OIDC issuer via .well-known/openid-configuration."""
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        client = _get_http_client()
        response = client.get(discovery_url)
        response.raise_for_status()
        config = response.json()
        jwks_uri = config.get("jwks_uri")
        if not jwks_uri:
            raise ValueError(f"No jwks_uri in OIDC discovery response from {discovery_url}")
        logger.info("oidc_discovery_complete", issuer=issuer, jwks_uri=jwks_uri)
        return jwks_uri
    except httpx.HTTPError as e:
        logger.error("oidc_discovery_failed", issuer=issuer, error=str(e))
        raise ValueError(f"OIDC discovery failed for {issuer}: {e}") from e


def _fetch_jwks() -> dict[str, Any]:
    global _jwks_cache

    with _cache_lock:
        now = time.time()
        if _jwks_cache and (now - _jwks_cache.fetched_at) < JWKS_CACHE_TTL_SECONDS:
            return _jwks_cache.keys

        jwks_uri = _get_jwks_uri()
        logger.info("fetching_jwks", uri=jwks_uri)

        try:
            client = _get_http_client()
            response = client.get(jwks_uri)
            response.raise_for_status()
            jwks = response.json()
        except httpx.HTTPError as e:
            logger.error("jwks_fetch_failed", error=str(e))
            if _jwks_cache:
                logger.warning("using_stale_jwks_cache")
                return _jwks_cache.keys
            raise

        keys_by_kid = {key["kid"]: key for key in jwks.get("keys", [])}
        _jwks_cache = JWKSCache(keys=keys_by_kid, fetched_at=now)

        logger.info("jwks_cached", key_count=len(keys_by_kid))
        return keys_by_kid


def _get_signing_key(token: str) -> dict[str, Any]:
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise ValueError(f"Invalid token header: {e}") from e
    
    kid = unverified_header.get("kid")
    if not kid:
        raise ValueError("Token missing 'kid' header")
    
    jwks = _fetch_jwks()
    if kid not in jwks:
        global _jwks_cache
        with _cache_lock:
            _jwks_cache = None
        jwks = _fetch_jwks()
        
        if kid not in jwks:
            raise ValueError(f"Unable to find signing key for kid: {kid}")
    
    return jwks[kid]


@dataclass
class Auth0TokenPayload:
    sub: str
    org_id: str | None
    email: str | None
    permissions: list[str]
    raw_claims: dict[str, Any]


def validate_auth0_token(token: str) -> Auth0TokenPayload:
    """Validate a JWT from any configured OIDC provider.

    Name kept as ``validate_auth0_token`` for backward compatibility —
    all call sites import this name. Works with Auth0, Keycloak, Azure AD,
    or any OIDC provider that publishes a JWKS endpoint.
    """
    settings = get_settings()

    if not settings.auth0_enabled:
        raise ValueError("OIDC authentication is not enabled")

    # Auth0 path: domain + audience required.
    # Generic OIDC path: oidc_issuer is sufficient.
    if not settings.oidc_issuer and (not settings.auth0_domain or not settings.auth0_audience):
        raise ValueError("Auth0 domain/audience or OIDC issuer must be configured")

    audience = settings.auth0_audience  # Works for both Auth0 and generic OIDC
    issuer = _get_issuer()

    signing_key = _get_signing_key(token)

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[settings.auth0_algorithms],
            audience=audience,
            issuer=issuer,
        )
    except JWTError as e:
        logger.warning("oidc_token_validation_failed", error=str(e), issuer=issuer)
        raise ValueError(f"Token validation failed: {e}") from e

    # Resolve org_id: check "org_id" (Auth0 orgs), then custom claim.
    org_claim = _get_org_claim()
    org_id = payload.get("org_id") or payload.get(org_claim)

    # Resolve email: standard claim, then Auth0 namespace fallback.
    email = payload.get("email")
    if not email and settings.auth0_domain:
        email = payload.get(f"{settings.auth0_domain}/email")

    permissions = payload.get("permissions", [])

    return Auth0TokenPayload(
        sub=payload["sub"],
        org_id=org_id,
        email=email,
        permissions=permissions,
        raw_claims=payload,
    )


# Alias for new code that prefers a generic name.
validate_oidc_token = validate_auth0_token


def fetch_userinfo(token: str) -> dict[str, Any]:
    """Fetch user profile from Auth0 /userinfo endpoint.

    Auth0 access tokens do NOT include email/email_verified by default.
    This endpoint returns the user's profile using the access token,
    providing the email and verification status needed for auto-linking.

    Results are cached per auth0 sub for USERINFO_CACHE_TTL_SECONDS to
    avoid hitting Auth0 rate limits when the frontend fires parallel requests.
    """
    try:
        unverified = jwt.get_unverified_claims(token)
        sub = unverified.get("sub", "")
    except JWTError:
        sub = ""

    now = time.time()
    with _cache_lock:
        if sub and sub in _userinfo_cache:
            entry = _userinfo_cache[sub]
            if (now - entry.fetched_at) < USERINFO_CACHE_TTL_SECONDS:
                return entry.data

    settings = get_settings()
    if settings.oidc_issuer:
        # Generic OIDC: derive userinfo from issuer (standard path)
        userinfo_url = f"{settings.oidc_issuer.rstrip('/')}/protocol/openid-connect/userinfo"
    else:
        userinfo_url = f"https://{settings.auth0_domain}/userinfo"

    try:
        client = _get_http_client()
        response = client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        data = response.json()
        if sub:
            with _cache_lock:
                _userinfo_cache[sub] = _UserinfoEntry(data=data, fetched_at=now)
        return data
    except httpx.HTTPError as e:
        logger.warning("userinfo_fetch_failed", error=str(e))
        with _cache_lock:
            if sub and sub in _userinfo_cache:
                return _userinfo_cache[sub].data
        return {}


def clear_jwks_cache() -> None:
    global _jwks_cache
    with _cache_lock:
        _jwks_cache = None
    logger.info("jwks_cache_cleared")
