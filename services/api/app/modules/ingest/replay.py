import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.base import get_db_session
from app.logging_config import get_logger

logger = get_logger(__name__)


async def check_idempotency_key(db: AsyncSession, key: str, ttl_seconds: int) -> bool:
    """Atomically insert an idempotency key. Returns True if new, False if duplicate.

    Uses INSERT ... ON CONFLICT DO NOTHING for atomic dedup — safe under
    concurrent requests and survives API restarts.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    result = await db.execute(
        text(
            "INSERT INTO ingest_idempotency_keys (key, expires_at) "
            "VALUES (:key, :expires_at) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": key, "expires_at": expires_at},
    )
    await db.flush()
    # rowcount == 1 means key was inserted (new), 0 means conflict (duplicate)
    return result.rowcount == 1


async def cleanup_expired_keys(db: AsyncSession) -> int:
    """Delete expired idempotency keys. Called periodically, not on every request."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        text("DELETE FROM ingest_idempotency_keys WHERE expires_at <= :now"),
        {"now": now},
    )
    return result.rowcount


async def verify_ingest_replay(
    request: Request,
    x_heimdex_timestamp: str | None = Header(None),
    x_heimdex_idempotency_key: str | None = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> None:
    settings = get_settings()

    if settings.ingest_require_timestamp:
        if not x_heimdex_timestamp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing X-Heimdex-Timestamp header",
            )
        try:
            request_ts = int(x_heimdex_timestamp)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Heimdex-Timestamp must be an integer (unix seconds)",
            ) from None
        server_ts = int(time.time())
        skew = abs(server_ts - request_ts)
        if skew > settings.ingest_timestamp_skew_seconds:
            logger.warning(
                "ingest_timestamp_rejected",
                request_ts=request_ts,
                server_ts=server_ts,
                skew=skew,
                max_skew=settings.ingest_timestamp_skew_seconds,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Request timestamp too far from server time (skew={skew}s, max={settings.ingest_timestamp_skew_seconds}s)",
            )

    if settings.ingest_require_idempotency and not x_heimdex_idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Heimdex-Idempotency-Key header",
        )

    if x_heimdex_idempotency_key:
        is_new = await check_idempotency_key(
            db,
            x_heimdex_idempotency_key,
            settings.ingest_idempotency_ttl_seconds,
        )
        if not is_new:
            logger.warning(
                "ingest_idempotency_replay",
                idempotency_key=x_heimdex_idempotency_key,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate request (idempotency key already used)",
            )
