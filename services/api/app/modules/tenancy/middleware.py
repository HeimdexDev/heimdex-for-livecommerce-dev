import re
from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.logging_config import get_logger
from app.modules.tenancy.context import OrgContext, org_context

logger = get_logger(__name__)

SUBDOMAIN_PATTERN = re.compile(
    r"^([a-z0-9][a-z0-9-]*[a-z0-9])\.app\."
    r"(?:heimdex\.(?:local|co)|heimdexdemo\.dev)$"
)
LOCALHOST_PATTERN = re.compile(r"^localhost(:\d+)?$")

HEALTH_PATHS = {"/health", "/healthz", "/ready"}


class TenancyError:
    LOCALHOST = "localhost"
    INVALID_FORMAT = "invalid_format"
    MISSING_SUBDOMAIN = "missing_subdomain"


def extract_org_slug(host: str) -> tuple[str | None, str | None]:
    """
    Extract org slug from Host header.
    
    Returns: (org_slug, error_code)
    - (slug, None) on success
    - (None, error_code) on failure
    """
    host_lower = host.lower()
    host_no_port = host_lower.split(":")[0]
    
    if LOCALHOST_PATTERN.match(host_lower):
        return None, TenancyError.LOCALHOST
    
    match = SUBDOMAIN_PATTERN.match(host_no_port)
    if match:
        return match.group(1), None
    
    if "heimdex" in host_lower:
        return None, TenancyError.MISSING_SUBDOMAIN
    
    return None, TenancyError.INVALID_FORMAT


class TenancyMiddleware:
    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in HEALTH_PATHS or path.startswith("/internal/"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("utf-8")
        
        org_slug, error_code = extract_org_slug(host)
        
        scope["state"] = scope.get("state", {})
        scope["state"]["org_slug"] = org_slug
        scope["state"]["tenancy_error"] = error_code
        
        if error_code:
            logger.warning(
                "tenancy_host_rejected",
                host=host,
                error=error_code,
                path=path,
            )
        
        await self.app(scope, receive, send)


ERROR_MESSAGES = {
    TenancyError.LOCALHOST: (
        "Multi-tenancy requires org subdomain. "
        "Use http://{org}.app.heimdex.local:8000 instead of localhost. "
        "Add '127.0.0.1 {org}.app.heimdex.local' to /etc/hosts."
    ),
    TenancyError.INVALID_FORMAT: (
        "Invalid Host header format. "
        "Expected: {org}.app.heimdex.local (dev), "
        "{org}.app.heimdexdemo.dev (staging), or {org}.app.heimdex.co (prod)"
    ),
    TenancyError.MISSING_SUBDOMAIN: (
        "Missing organization subdomain in Host header. "
        "Expected: {org}.app.heimdex.local, got host without org prefix."
    ),
}


async def get_current_org(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OrgContext:
    from app.modules.orgs.models import Org
    
    org_slug = getattr(request.state, "org_slug", None)
    tenancy_error = getattr(request.state, "tenancy_error", None)
    
    if not org_slug:
        host = request.headers.get("host", "")
        
        if tenancy_error:
            error_msg = ERROR_MESSAGES.get(tenancy_error, "Invalid Host header")
            logger.warning(
                "tenancy_rejected",
                host=host,
                error=tenancy_error,
                path=request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )
        
        org_slug, error_code = extract_org_slug(host)
        if not org_slug:
            error_msg = ERROR_MESSAGES.get(
                error_code or TenancyError.INVALID_FORMAT,
                "Invalid Host header"
            )
            logger.warning("tenancy_rejected", host=host, error=error_code)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )
    
    result = await db.execute(select(Org).where(Org.slug == org_slug))
    org = result.scalar_one_or_none()
    
    if not org:
        logger.warning("org_not_found", slug=org_slug)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization '{org_slug}' not found. Verify the subdomain is correct.",
        )
    
    ctx = OrgContext(
        org_id=org.id,
        org_slug=org.slug,
        auth0_org_id=getattr(org, "auth0_org_id", None),
    )
    org_context.set(ctx)
    
    logger.debug("org_context_resolved", org_id=str(org.id), slug=org.slug)
    return ctx
