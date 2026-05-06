"""Refinement-chain DB queries.

Kept separate from :mod:`app.modules.shorts_render.repository` so the
existing repository's surface stays untouched (everything except
``complete_idempotent`` is unchanged by PR 4). Refinement is a
distinct concern: it creates child render rows and walks the
parent→child link.

All methods are async, accept an :class:`AsyncSession`, and contain
no business logic. The orchestration (when to refine, what to
build) lives in :mod:`app.modules.shorts_render.refinement_service`.

Loose-coupling note: this module has zero ``app.modules.*`` imports
beyond ``shorts_render`` itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_render.models import ShortsRenderJob


async def lock_parent_or_none(
    session: AsyncSession,
    parent_job_id: UUID,
) -> ShortsRenderJob | None:
    """Acquire a row lock on the parent render with ``SKIP LOCKED``.

    Returns the row when the lock was acquired. Returns ``None`` when:
      - The row doesn't exist (deleted between callback and refinement).
      - Another worker already holds the lock (concurrent callback).

    Use this BEFORE running the refinement guards so two concurrent
    callbacks don't both pass the "not yet refined" check and create
    duplicate child rows.

    The caller is responsible for committing or rolling back; the
    lock releases on commit/rollback.
    """
    stmt = (
        select(ShortsRenderJob)
        .where(ShortsRenderJob.id == parent_job_id)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_refined_child(
    session: AsyncSession,
    *,
    parent: ShortsRenderJob,
    refined_input_spec: dict[str, Any],
) -> ShortsRenderJob:
    """Insert a child render row pointing back at the parent.

    Inherits ``org_id``, ``user_id``, ``video_id``, ``title``, and
    ``expires_at`` from the parent. ``refinement_source`` is hard-set
    to ``'whisper'`` (the only source that creates child rows; manual
    edits update the existing row in place via a separate endpoint).

    The new row's ``status`` is the model default (``'queued'``);
    the caller is expected to publish to SQS after committing.
    """
    child = ShortsRenderJob(
        org_id=parent.org_id,
        user_id=parent.user_id,
        video_id=parent.video_id,
        title=parent.title,
        input_spec=refined_input_spec,
        expires_at=parent.expires_at,
        composition_hash=None,  # refined composition has different hash;
                                # leave NULL so dedupe doesn't collapse
                                # a refined job with its parent.
        refined_from_render_job_id=parent.id,
        refinement_source="whisper",
    )
    session.add(child)
    await session.flush()
    return child


async def link_parent_to_child(
    session: AsyncSession,
    *,
    parent_id: UUID,
    child_id: UUID,
) -> None:
    """Set ``parent.replaced_by_render_job_id = child_id``.

    Wizard polling reads ``replaced_by_render_job_id`` to follow the
    chain, so this link must be in place before the SQS publish or
    the operator briefly sees the parent as "still canonical" while
    the refined render is in flight. Acceptable race — the partial
    index covers this query, and the wizard polls every few seconds.
    """
    now = datetime.now(timezone.utc)
    await session.execute(
        update(ShortsRenderJob)
        .where(ShortsRenderJob.id == parent_id)
        .values(
            replaced_by_render_job_id=child_id,
            updated_at=now,
        )
    )
    await session.flush()


async def already_refined(
    session: AsyncSession,
    parent_job_id: UUID,
) -> bool:
    """Cheap pre-lock check: has this parent already been refined?

    Returns ``True`` when ``replaced_by_render_job_id IS NOT NULL``.
    Drives the partial index added by migration 056.

    Use as a fast-path filter before acquiring the row lock; even if
    a concurrent caller is mid-refinement (lock held), this returns
    ``False`` and we proceed to the lock check, which then returns
    ``None`` (row locked → caller skips). No double-fire.
    """
    stmt = (
        select(ShortsRenderJob.replaced_by_render_job_id)
        .where(ShortsRenderJob.id == parent_job_id)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return row is not None
