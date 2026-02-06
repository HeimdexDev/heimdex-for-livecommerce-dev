"""
Auth0 OIDC token validation service.

Validates JWT access tokens issued by Auth0 using JWKS (RS256).
Caches JWKS keys to avoid repeated HTTP calls.
"""
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


@dataclass
class JWKSCache:
    keys: dict[str, Any]
    fetched_at: float


_jwks_cache: JWKSCache | None = None


def _get_jwks_uri() -> str:
    settings = get_settings()
    return f"https://{settings.auth0_domain}/.well-known/jwks.json"


def _fetch_jwks() -> dict[str, Any]:
    global _jwks_cache
    
    now = time.time()
    if _jwks_cache and (now - _jwks_cache.fetched_at) < JWKS_CACHE_TTL_SECONDS:
        return _jwks_cache.keys
    
    jwks_uri = _get_jwks_uri()
    logger.info("fetching_jwks", uri=jwks_uri)
    
    try:
        with httpx.Client(timeout=10.0) as client:
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
    settings = get_settings()
    
    if not settings.auth0_enabled:
        raise ValueError("Auth0 is not enabled")
    
    if not settings.auth0_domain or not settings.auth0_audience:
        raise ValueError("Auth0 domain and audience must be configured")
    
    signing_key = _get_signing_key(token)
    
    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[settings.auth0_algorithms],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
    except JWTError as e:
        logger.warning("auth0_token_validation_failed", error=str(e))
        raise ValueError(f"Token validation failed: {e}") from e
    
    org_id = payload.get(settings.auth0_org_claim)
    email = payload.get("email") or payload.get(f"{settings.auth0_domain}/email")
    permissions = payload.get("permissions", [])
    
    return Auth0TokenPayload(
        sub=payload["sub"],
        org_id=org_id,
        email=email,
        permissions=permissions,
        raw_claims=payload,
    )


def clear_jwks_cache() -> None:
    global _jwks_cache
    _jwks_cache = None
    logger.info("jwks_cache_cleared")
