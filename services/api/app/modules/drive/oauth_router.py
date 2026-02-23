import hashlib
import hmac
import json
import logging
import os
import time
from typing import Annotated
from urllib.parse import urlencode

import requests as http_requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.modules.drive.repository import DriveConnectionRepository, DriveSecretRepository
from app.modules.drive.schemas import DriveOAuthStatusResponse
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org

logger = logging.getLogger(__name__)

oauth_router = APIRouter(prefix="/drive/oauth", tags=["drive-oauth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"

# HMAC-signed state tokens (stateless CSRF protection)
_STATE_TTL_SECONDS = 600  # 10 minutes


def _require_oauth_configured() -> None:
    settings = get_settings()
    if not settings.drive_connector_enabled or not settings.google_oauth_client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Google Drive OAuth is not configured",
        )


def _sign_state(org_id: str, encryption_key: str) -> str:
    """Create an HMAC-signed state token embedding org_id and timestamp."""
    ts = str(int(time.time()))
    nonce = os.urandom(8).hex()
    payload = f"{org_id}:{ts}:{nonce}"
    key = bytes.fromhex(encryption_key)
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}:{sig}"


def _verify_state(state: str, encryption_key: str) -> str:
    """Verify HMAC-signed state token. Returns org_id or raises."""
    parts = state.split(":")
    if len(parts) != 4:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state")

    org_id, ts, nonce, sig = parts
    payload = f"{org_id}:{ts}:{nonce}"
    key = bytes.fromhex(encryption_key)
    expected_sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()[:32]

    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state signature")

    elapsed = int(time.time()) - int(ts)
    if elapsed > _STATE_TTL_SECONDS or elapsed < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="State token expired")

    return org_id


@oauth_router.get("/authorize")
async def authorize(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    _: Annotated[None, Depends(_require_oauth_configured)],
):
    settings = get_settings()
    state = _sign_state(str(org_ctx.org_id), settings.drive_sa_encryption_key)

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": DRIVE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    authorize_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return {"authorize_url": authorize_url}


@oauth_router.get("/callback")
async def callback(
    code: str,
    state: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_oauth_configured)],
):
    settings = get_settings()
    org_id_str = _verify_state(state, settings.drive_sa_encryption_key)

    # Exchange authorization code for tokens
    token_response = http_requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if token_response.status_code != 200:
        logger.error(
            "oauth_token_exchange_failed",
            extra={"status": token_response.status_code, "body": token_response.text[:500]},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to exchange authorization code",
        )

    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No refresh token received. Try revoking access and reconnecting.",
        )

    # Get user email from userinfo
    userinfo_response = http_requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    google_email = "unknown"
    if userinfo_response.status_code == 200:
        google_email = userinfo_response.json().get("email", "unknown")

    # Encrypt the token payload
    token_payload = json.dumps({
        "refresh_token": refresh_token,
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
    })

    key = bytes.fromhex(settings.drive_sa_encryption_key)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    encrypted_value = aesgcm.encrypt(nonce, token_payload.encode(), None)

    # Store in drive_secrets as oauth_token type
    from uuid import UUID
    secret_repo = DriveSecretRepository(db)
    await secret_repo.upsert(
        org_id=UUID(org_id_str),
        encrypted_value=encrypted_value,
        nonce=nonce,
        impersonate_email=google_email,
        secret_type="oauth_token",
    )
    await db.commit()

    logger.info(
        "oauth_connected",
        extra={"org_id": org_id_str, "google_email": google_email},
    )

    return RedirectResponse(url="/sync?drive_connected=true", status_code=302)


@oauth_router.get("/status", response_model=DriveOAuthStatusResponse)
async def oauth_status(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_oauth_configured)],
):
    secret_repo = DriveSecretRepository(db)
    secret = await secret_repo.get_by_org(org_ctx.org_id, secret_type="oauth_token")
    if secret is None:
        return DriveOAuthStatusResponse(connected=False)
    return DriveOAuthStatusResponse(
        connected=True,
        google_email=secret.impersonate_email,
        connected_at=secret.created_at,
    )


@oauth_router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_oauth_configured)],
):
    settings = get_settings()
    secret_repo = DriveSecretRepository(db)
    secret = await secret_repo.get_by_org(org_ctx.org_id, secret_type="oauth_token")

    if secret is not None:
        # Attempt to revoke the token at Google
        try:
            key = bytes.fromhex(settings.drive_sa_encryption_key)
            aesgcm = AESGCM(key)
            decrypted = aesgcm.decrypt(secret.nonce, secret.encrypted_value, None)
            token_data = json.loads(decrypted)
            refresh_token = token_data.get("refresh_token")
            if refresh_token:
                http_requests.post(
                    GOOGLE_REVOKE_URL,
                    params={"token": refresh_token},
                    timeout=10,
                )
        except Exception:
            logger.warning("oauth_revoke_failed", exc_info=True)

        await secret_repo.delete_by_org_and_type(org_ctx.org_id, "oauth_token")

    # Mark all folder-scoped connections as disconnected
    conn_repo = DriveConnectionRepository(db)
    connections = await conn_repo.list_by_org(org_ctx.org_id)
    for conn in connections:
        if conn.scope_type == "folder" and conn.status == "active":
            conn.status = "disconnected"
    await db.commit()
