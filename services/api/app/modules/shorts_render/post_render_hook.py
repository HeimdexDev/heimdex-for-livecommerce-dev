"""Post-render hook entry point.

Imported and called by :mod:`app.modules.shorts_render.internal_router`
on the render-completion callback path. Three responsibilities:

1. Master flag check (``WHISPER_REFINE_ENABLED``).
2. Per-org rollout bucket check.
3. Hand off to :mod:`.refinement_service` (fire-and-forget).

This module deliberately stays thin — it owns the routing decision,
not the orchestration. Tests can mock this module's
``schedule_refinement_if_eligible`` to verify the router wiring
without exercising the whole Whisper + S3 + SQS stack.

Loose-coupling rules:
- Imports from ``app.lib.rollout`` and the local
  ``refinement_service`` only.
- NEVER raises out — every exception is logged + swallowed so a
  bug in routing logic doesn't 500 the worker callback.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.config import get_settings
from app.lib.rollout import is_in_rollout
from app.modules.shorts_render import refinement_service

logger = logging.getLogger(__name__)


def schedule_refinement_if_eligible(
    *,
    parent_job_id: UUID,
    org_id: UUID,
) -> None:
    """Schedule a Whisper refinement task if the parent is eligible.

    Returns immediately. The actual orchestration runs as a
    fire-and-forget asyncio task inside
    :func:`refinement_service.schedule_refinement`.

    The ``did_complete`` idempotency check at the callback level
    (:func:`ShortsRenderJobRepository.complete_idempotent`) ensures
    this is called at most once per render even on SQS redelivery.

    Args:
        parent_job_id: The render that just completed. The
            refinement runner will re-fetch this row inside its own
            session — pass the id, not the ORM instance, since the
            request session may close before the runner runs.
        org_id: Used for rollout bucketing. Hashed deterministically
            so a given org consistently is or isn't in the rollout.

    Failure modes (all return without scheduling):
        - master flag off → silent no-op.
        - org outside rollout → silent no-op.
        - any unexpected exception → logged, no-op.
    """
    try:
        settings = get_settings()

        if not settings.auto_shorts_product_v2_whisper_refine_enabled:
            return

        rollout_pct = int(
            settings.auto_shorts_product_v2_whisper_rollout_pct or 0
        )
        if not is_in_rollout(key=str(org_id), rollout_pct=rollout_pct):
            logger.debug(
                "whisper_refine_outside_rollout",
                extra={
                    "parent_job_id": str(parent_job_id),
                    "org_id": str(org_id),
                    "rollout_pct": rollout_pct,
                },
            )
            return

        refinement_service.schedule_refinement(parent_job_id)
        logger.info(
            "whisper_refine_scheduled",
            extra={
                "parent_job_id": str(parent_job_id),
                "org_id": str(org_id),
            },
        )
    except Exception:
        # Defense in depth: this function is called from the worker
        # callback handler; raising here would 500 the worker's PUT
        # and trigger an SQS retry. Swallow + log instead.
        logger.exception(
            "whisper_refine_hook_failed",
            extra={"parent_job_id": str(parent_job_id)},
        )
