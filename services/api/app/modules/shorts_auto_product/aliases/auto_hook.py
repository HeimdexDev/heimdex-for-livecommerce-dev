"""Fire-and-forget alias gen after enumeration.
Mirrors image_caption/service.py:330-360 fire-and-forget pattern.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

logger = logging.getLogger(__name__)

# Strong-ref so the fire-and-forget task isn't GC'd mid-flight
# (same as image_caption._BACKGROUND_TASKS).
_BG_TASKS: set[asyncio.Task] = set()


def schedule_alias_generation(
    *, org_id: UUID, video_db_id: UUID, settings,
) -> None:
    """Fire-and-forget. Returns immediately; alias gen runs in bg.
    No-op when the flag is off.
    """
    if not getattr(
        settings,
        "auto_shorts_product_v2_alias_auto_hook_enabled",
        False,
    ):
        return

    async def _runner() -> None:
        try:
            from app.db.base import get_async_session_factory
            from app.modules.shorts_auto_product.aliases.backfill_core import (
                backfill_aliases_for_video,
            )

            session_factory = get_async_session_factory()
            n = await backfill_aliases_for_video(
                session_factory=session_factory,
                org_id=org_id,
                video_db_id=video_db_id,
                settings=settings,
            )
            logger.info(
                "alias_auto_hook_done",
                extra={"video_db_id": str(video_db_id), "processed": n},
            )
        except Exception:  # noqa: BLE001 — fire-and-forget, never raise
            logger.exception(
                "alias_auto_hook_runner_failed",
                extra={
                    "org_id": str(org_id),
                    "video_db_id": str(video_db_id),
                },
            )

    task = asyncio.create_task(_runner())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)