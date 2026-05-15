"""
Schema readiness check for the agent_intents feature.

Prevents 500 errors when AGENT_INTENTS_ENABLED=true but migration
006_add_agent_intents_table has not been applied.

Design: Approach A - startup check sets a cached boolean. Endpoints
use a lightweight FastAPI dependency that checks the cached value.
The check is also re-verified with a TTL cache (60s) so that if
migrations are applied while the app is running, it self-heals.

Returns 503 with a clear JSON body when the table is missing.
"""

import time

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.logging_config import get_logger

logger = get_logger(__name__)

_MIGRATION_CMD = "docker compose exec api alembic upgrade head"

# Cached state
_schema_ready: bool = False
_last_check_time: float = 0.0
_CHECK_TTL_SECONDS: float = 60.0


async def check_agent_intents_table(engine: AsyncEngine) -> bool:
    """Check if the agent_intents table exists in the database.

    Uses Postgres to_regclass() for a fast, non-locking check.
    """
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT to_regclass('public.agent_intents')"))
            return result.scalar() is not None
    except Exception as e:
        logger.warning(
            "agent_intents_schema_check_failed",
            error=str(e),
        )
        return False


async def startup_check_agent_intents_schema(engine: AsyncEngine, enabled: bool) -> None:
    """Run at app startup. Sets cached state and logs appropriately."""
    global _schema_ready, _last_check_time

    if not enabled:
        logger.debug("agent_intents_disabled_skipping_schema_check")
        return

    _schema_ready = await check_agent_intents_table(engine)
    _last_check_time = time.monotonic()

    if _schema_ready:
        logger.info("agent_intents_schema_ready")
    else:
        logger.error(
            "agent_intents_schema_missing",
            message=(
                "AGENT_INTENTS_ENABLED=true but 'agent_intents' table does not exist. "
                "Agent intent endpoints will return 503 until migration is applied. "
                f"Run: {_MIGRATION_CMD}"
            ),
            migration="006_add_agent_intents_table",
            fix_command=_MIGRATION_CMD,
        )


async def _refresh_if_stale(engine: AsyncEngine) -> None:
    """Re-check schema if TTL has expired (self-healing)."""
    global _schema_ready, _last_check_time

    now = time.monotonic()
    if now - _last_check_time >= _CHECK_TTL_SECONDS:
        _schema_ready = await check_agent_intents_table(engine)
        _last_check_time = now
        if _schema_ready:
            logger.info(
                "agent_intents_schema_now_ready",
                message="Schema detected after TTL refresh",
            )


def require_agent_intents_schema() -> None:
    """Synchronous check of cached state. Call in endpoint after feature flag check.

    Raises HTTPException 503 if schema is not ready.
    """
    if not _schema_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Agent intents service unavailable: database migration required. "
                f"Run: {_MIGRATION_CMD}"
            ),
        )


def _reset_cache(*, ready: bool = False) -> None:
    """For testing: allow resetting cached state."""
    global _schema_ready, _last_check_time
    _schema_ready = ready
    _last_check_time = 0.0
