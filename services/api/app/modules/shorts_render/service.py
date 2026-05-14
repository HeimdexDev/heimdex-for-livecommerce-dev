"""Shorts render job service layer.

Orchestrates render job CRUD with scene boundary validation,
SQS publishing (fire-and-forget), and S3 cleanup on delete.

Also exposes a module-level ``cleanup_expired_renders`` entry point
used by the nightly cleanup CLI. It lives here (not on the request-scoped
``ShortsRenderService``) so the CLI doesn't have to construct the full
service dependency graph.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import HTTPException, status

# How long a just-created render job is visible to the dedupe query.
# Long enough to kill accidental double-clicks, React dev-mode double
# renders, and mobile-client network retries. Short enough not to block
# intentional re-submission (e.g. the user edits fonts and resubmits).
_DEDUPE_WINDOW_SECONDS = 30


def compute_composition_hash(composition: Any) -> str:
    """Deterministic sha256 of a composition spec.

    Uses ``sort_keys=True`` so Pydantic dict-ordering drift across
    versions never changes the hash. Returned as 64 hex chars — fits
    the ``composition_hash VARCHAR(64)`` column exactly.
    """
    if hasattr(composition, "model_dump"):
        body = composition.model_dump()
    else:
        body = composition
    canonical = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

# Defensive regex for the ONLY S3 key shape the cleanup sweep is allowed to
# touch. Enforced at delete time so a future bug that writes something other
# than a shorts render output into `output_s3_key` (e.g., a scene thumbnail
# path, a drive proxy, a raw upload) will be skipped with a warning instead
# of silently deleted. Matches:
#     {org_uuid}/shorts/renders/{job_uuid}/output.mp4
# Case-insensitive on the UUID hex to be forgiving of any capitalization drift.
_SAFE_SHORTS_OUTPUT_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/shorts/renders/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"/[^/]+\.mp4$",
    re.IGNORECASE,
)


def _is_safe_shorts_output_key(key: str) -> bool:
    """Is this S3 key shaped like a shorts-render worker output?"""
    return bool(_SAFE_SHORTS_OUTPUT_KEY_RE.match(key))

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.shorts_render.models import ShortsRenderJob
from app.modules.shorts_render.repository import ShortsRenderJobRepository
from app.modules.shorts_render.schemas import (
    RenderJobCreate,
    RenderJobListResponse,
    RenderJobResponse,
)

logger = get_logger(__name__)


@dataclass
class CleanupResult:
    """Outcome of a single ``cleanup_expired_renders`` invocation.

    - ``total_expired``: jobs matched as expired (with + without output)
    - ``s3_deleted``: S3 objects successfully deleted
    - ``s3_skipped_not_found``: S3 keys that were already gone (idempotent)
    - ``s3_failed``: S3 deletes that raised an unexpected error
    - ``s3_skipped_unsafe_key``: jobs whose output_s3_key didn't match the
      shorts-render pattern, so cleanup refused to delete them (safety belt
      against the bucket accidentally holding a video / scene / thumbnail
      path under output_s3_key). These rows are NOT DB-deleted — a human
      should investigate.
    - ``db_deleted``: DB rows removed
    - ``dry_run``: True when nothing was actually deleted
    - ``failed_keys``: list of ``(s3_key, error_message)`` for failed deletes
    - ``unsafe_keys``: list of keys that tripped the safety pattern check
    """
    total_expired: int = 0
    s3_deleted: int = 0
    s3_skipped_not_found: int = 0
    s3_failed: int = 0
    s3_skipped_unsafe_key: int = 0
    db_deleted: int = 0
    dry_run: bool = False
    failed_keys: list[tuple[str, str]] = field(default_factory=list)
    unsafe_keys: list[str] = field(default_factory=list)


async def cleanup_expired_renders(
    repository: ShortsRenderJobRepository,
    s3_client: Any,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> CleanupResult:
    """Delete expired shorts-render jobs from S3 and the DB.

    Per-job atomic: a failure on job N does not abort the sweep for jobs
    N+1..end. S3 deletes that return NoSuchKey are treated as already-done
    (idempotent). DB rows are only removed after the corresponding S3
    delete succeeds (or the object was already missing) — never orphan a
    file by deleting the row first.

    Separately drops DB rows for failed/orphaned jobs that never produced
    an S3 output; those would otherwise accumulate forever because
    ``list_expired()`` filters on ``output_s3_key IS NOT NULL``.

    Args:
        repository: bound to an AsyncSession; caller owns the commit
        s3_client: anything with a ``delete(key)`` method. Typed as Any so
            the CLI can pass the real ``S3Client`` while tests pass a mock
            without satisfying an import-time protocol.
        dry_run: when True, iterate and log but do not call S3 or the DB
        now: override wall-clock for tests. Defaults to ``datetime.now(utc)``.
    """
    current_time = now or datetime.now(timezone.utc)
    result = CleanupResult(dry_run=dry_run)

    with_output = await repository.list_expired(current_time)
    without_output = await repository.list_expired_without_output(current_time)
    result.total_expired = len(with_output) + len(without_output)

    if result.total_expired == 0:
        logger.info("cleanup_shorts_renders_noop", now=current_time.isoformat())
        return result

    logger.info(
        "cleanup_shorts_renders_started",
        dry_run=dry_run,
        now=current_time.isoformat(),
        with_output=len(with_output),
        without_output=len(without_output),
    )

    # --- Jobs with output: S3 delete → DB delete ---
    for job in with_output:
        s3_key = job.output_s3_key
        if s3_key is None:
            # list_expired() filters on IS NOT NULL; this is defensive only
            continue

        # Safety belt: refuse to delete any key outside the shorts-render
        # output namespace, even in dry-run logs. Protects against the
        # catastrophic case where something upstream ever wrote a
        # video/scene/thumbnail path into this column.
        if not _is_safe_shorts_output_key(s3_key):
            result.s3_skipped_unsafe_key += 1
            result.unsafe_keys.append(s3_key)
            logger.error(
                "cleanup_refused_unsafe_key",
                job_id=str(job.id),
                s3_key=s3_key,
                reason="does not match {org_uuid}/shorts/renders/{job_uuid}/*.mp4",
            )
            continue

        if dry_run:
            logger.info(
                "cleanup_would_delete",
                job_id=str(job.id),
                s3_key=s3_key,
                expires_at=job.expires_at.isoformat() if job.expires_at else None,
            )
            continue

        try:
            s3_client.delete(s3_key)
            result.s3_deleted += 1
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                # Already gone — still fine to drop the DB row
                result.s3_skipped_not_found += 1
                logger.info(
                    "cleanup_s3_already_gone",
                    job_id=str(job.id),
                    s3_key=s3_key,
                )
            else:
                result.s3_failed += 1
                result.failed_keys.append((s3_key, str(e)))
                logger.warning(
                    "cleanup_s3_delete_failed",
                    job_id=str(job.id),
                    s3_key=s3_key,
                    error=str(e),
                )
                # Skip DB delete so the row stays and we can retry next run
                continue

        deleted = await repository.delete_one_by_id_internal(cast(UUID, job.id))
        if deleted:
            result.db_deleted += 1

    # --- Failed / orphaned jobs: DB delete only (no S3 key to touch) ---
    for job in without_output:
        if dry_run:
            logger.info(
                "cleanup_would_delete_db_only",
                job_id=str(job.id),
                status=job.status,
                expires_at=job.expires_at.isoformat() if job.expires_at else None,
            )
            continue

        deleted = await repository.delete_one_by_id_internal(cast(UUID, job.id))
        if deleted:
            result.db_deleted += 1

    logger.info(
        "cleanup_shorts_renders_completed",
        dry_run=dry_run,
        total_expired=result.total_expired,
        s3_deleted=result.s3_deleted,
        s3_skipped_not_found=result.s3_skipped_not_found,
        s3_failed=result.s3_failed,
        s3_skipped_unsafe_key=result.s3_skipped_unsafe_key,
        db_deleted=result.db_deleted,
    )

    return result


# 1 hour TTL — long enough for an operator to open the editor, edit
# subtitles, and click download without re-fetching, but short enough
# to bound exposure if the URL leaks. Mirrors the existing crop URL
# TTL on the catalog gallery (see _CROP_URL_TTL_SECONDS).
_PLAYBACK_URL_TTL_SECONDS = 3600


async def _build_playback_url(job: ShortsRenderJob) -> str | None:
    """Return a presigned S3 URL the browser can use directly for
    ``<video src>`` / download anchors, or ``None`` when the job
    hasn't completed.

    Why presigned over the api ``/download`` endpoint: that endpoint
    requires Bearer auth, which the browser cannot attach to a
    ``<video>`` element or an anchor click. Returning the api path
    in ``download_url`` produced silent 401s on every inline play
    (staging incident 2026-05-06). Presigned URLs work without
    auth headers and natively support HTTP Range requests.
    """
    if job.status != "completed" or not job.output_s3_key:
        return None
    from app.config import get_settings
    from app.storage.s3 import S3Client

    settings = get_settings()
    s3 = S3Client(bucket=settings.drive_s3_bucket)
    return await s3.generate_presigned_url_async(
        job.output_s3_key,
        expires_in=_PLAYBACK_URL_TTL_SECONDS,
    )


def _to_response(
    job: ShortsRenderJob,
    download_url: str | None = None,
    *,
    effective_render_job_id: UUID | None = None,
) -> RenderJobResponse:
    # Extract thumbnail from first scene clip in input_spec
    thumb_vid = None
    thumb_scene = None
    try:
        clips = job.input_spec.get("scene_clips", [])
        if clips:
            thumb_vid = clips[0].get("video_id")
            thumb_scene = clips[0].get("scene_id")
    except (AttributeError, IndexError, TypeError):
        pass

    return RenderJobResponse(
        id=cast(UUID, job.id),
        video_id=job.video_id,
        title=job.title,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        render_time_ms=job.render_time_ms,
        output_duration_ms=job.output_duration_ms,
        output_size_bytes=job.output_size_bytes,
        error=job.error,
        download_url=download_url,
        thumbnail_video_id=thumb_vid,
        thumbnail_scene_id=thumb_scene,
        # Refinement chain (migration 056). Read directly off the ORM
        # row — both pointers and the source flag are nullable
        # columns so existing rows remain unaffected.
        replaced_by_render_job_id=job.replaced_by_render_job_id,
        refined_from_render_job_id=job.refined_from_render_job_id,
        refinement_source=job.refinement_source,
        # ``effective_render_job_id`` is None when ``job`` IS the
        # leaf (the common case — listing filters to leaves; single-
        # get on a leaf passes None through). Populated by callers
        # who fetched an intermediate row and resolved its chain.
        effective_render_job_id=effective_render_job_id,
    )


class ShortsRenderService:
    def __init__(self, repository: ShortsRenderJobRepository, scene_search: Any):
        self.repository = repository
        self.scene_search = scene_search

    async def create_render_job(
        self,
        org_id: UUID,
        user_id: UUID,
        payload: RenderJobCreate,
        *,
        dedupe_within_seconds: int | None = None,
        idempotency_key: str | None = None,
    ) -> RenderJobResponse:
        """Create a render job after validating scene boundaries.

        Implements implicit idempotency: if the same user submits a job
        with the same composition_hash within ``dedupe_within_seconds``
        (default :data:`_DEDUPE_WINDOW_SECONDS` = 30s), returns the
        existing job instead of creating a new one. Kills accidental
        double-clicks without blocking intentional re-renders.

        ``dedupe_within_seconds`` lets server-side retry paths widen the
        window past their lease horizon. Two concrete consumers:

        * The wizard child runner (``shorts_auto_product.children.runner``)
          claims a child for ``lease_seconds`` (default 300s); a crashed
          replica's lease takes that long to expire before another
          replica re-claims and retries the render. With the default 30s
          window the retry would fire AFTER the dedupe closed → duplicate
          render row. The runner passes ``lease_seconds + 60``.
        * The track-worker's ``/internal/products/{id}/render`` callback
          has the same lease-expiry retry shape (separate PR).

        HTTP-initiated callers (``POST /api/shorts/render`` from the web
        client, the highlight-reel router, the v1 auto-shorts service)
        leave ``dedupe_within_seconds=None`` to keep the user-visible
        anti-double-click semantics — a longer window there would block
        legitimate re-submissions when the user edits + resubmits.

        Raises:
            ValueError: ``dedupe_within_seconds`` is negative. Zero is
                permitted and effectively disables dedupe (no row can
                be created in the future of "now").
        """
        if dedupe_within_seconds is not None and dedupe_within_seconds < 0:
            raise ValueError(
                f"dedupe_within_seconds must be >= 0; got "
                f"{dedupe_within_seconds}"
            )
        effective_dedupe_seconds = (
            dedupe_within_seconds
            if dedupe_within_seconds is not None
            else _DEDUPE_WINDOW_SECONDS
        )

        # 1. Validate scene boundaries via OpenSearch mget
        await self._validate_scene_clips(org_id, payload)

        # 2. Dedupe check — if this user just submitted the same
        #    composition, return that job instead of spawning a duplicate.
        composition_hash = compute_composition_hash(payload.composition)
        dedupe_since = datetime.now(timezone.utc) - timedelta(
            seconds=effective_dedupe_seconds,
        )
        existing = await self.repository.find_recent_duplicate(
            org_id=org_id,
            user_id=user_id,
            composition_hash=composition_hash,
            since=dedupe_since,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            logger.info(
                "render_job_idempotent_replay",
                job_id=str(existing.id),
                org_id=str(org_id),
                user_id=str(user_id),
                composition_hash=composition_hash,
                idempotency_key=idempotency_key,
                age_seconds=(
                    datetime.now(timezone.utc) - existing.created_at
                ).total_seconds(),
            )
            return _to_response(existing)

        # 3. Create DB record
        settings = get_settings()
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.shorts_render_expiry_days)

        job = await self.repository.create(
            org_id=org_id,
            user_id=user_id,
            video_id=payload.video_id,
            title=payload.title,
            input_spec=payload.composition.model_dump(),
            expires_at=expires_at,
            composition_hash=composition_hash,
            idempotency_key=idempotency_key,
        )

        logger.info(
            "render_job_created",
            job_id=str(job.id),
            org_id=str(org_id),
            user_id=str(user_id),
            video_id=payload.video_id,
            clip_count=len(payload.composition.scene_clips),
            subtitle_count=len(payload.composition.subtitles),
            composition_hash=composition_hash,
        )

        # 3a. Commit BEFORE publishing the SQS message.
        #
        # Background: shorts-render-worker's long-poll wakes within ~10ms
        # of an SQS publish; the worker then HTTPs back to the api in a
        # FRESH DB session to claim the job. That fresh session can only
        # see committed rows. If we publish before committing, the
        # worker can race ahead, get a 404, drop the message, and the
        # row stays stuck at status='queued' forever (staging incident
        # 2026-05-06: 4 of 5 wizard children stranded — the 1 that won
        # the race got lucky with timing). The one prior commit-time
        # was the dependency-injected session at FastAPI request end —
        # too late to be useful for a worker that's already polling.
        #
        # Committing here flushes the row to disk so subsequent worker
        # lookups see it. The caller's FastAPI dependency will commit
        # again at request end (no-op on an already-committed
        # transaction; SQLAlchemy starts a fresh transaction for any
        # further work in the same session).
        await self.repository.session.commit()

        # 3b. Publish SQS — if this fails, mark job as failed so it
        #     doesn't stay stuck in "queued" forever.
        try:
            from app.sqs_producer import publish_shorts_render_job

            publish_shorts_render_job(
                job_id=cast(UUID, job.id),
                org_id=org_id,
                video_id=payload.video_id,
                input_spec=payload.composition.model_dump(),
            )
        except Exception:
            logger.exception("sqs_shorts_render_publish_failed", job_id=str(job.id))
            await self.repository.update_status(
                cast(UUID, job.id),
                "failed",
                error="Failed to enqueue render job",
            )
            # The status update needs its own commit since we already
            # commited the original creation above.
            await self.repository.session.commit()
            job.status = "failed"
            job.error = "Failed to enqueue render job"

        return _to_response(job)

    async def get_render_job_record(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> ShortsRenderJob | None:
        """Get the raw DB record for a render job (org + user scoped)."""
        return await self.repository.get_by_id(org_id, user_id, job_id)

    async def get_render_job(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> RenderJobResponse:
        """Get a render job by ID. Populates download_url for completed jobs.

        Scoped to org AND user — a user cannot view another user's job
        in the same org even if they guess the UUID.

        Refinement-chain resolution: when the requested ``job_id`` is
        an intermediate render (its ``replaced_by_render_job_id`` is
        not NULL), the response keeps the requested row's metadata
        (so the caller can see "you asked for X") but the
        ``download_url`` and ``effective_render_job_id`` fields point
        to the chain's leaf. The FE uses ``effective_render_job_id``
        to redirect bookmark URLs onto the current canonical row.
        """
        job = await self.repository.get_by_id(org_id, user_id, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        # Most calls hit a leaf (the listing filters intermediates
        # out, so callers normally have leaf ids). Only walk when the
        # row points forward — saves a query on the common path.
        if job.replaced_by_render_job_id is None:
            download_url = await _build_playback_url(job)
            return _to_response(job, download_url=download_url)

        leaf = await self.repository.walk_to_leaf(org_id, user_id, job_id)
        if leaf is None or leaf.id == job.id:
            # Broken chain or somehow walked back to ourselves —
            # fall back to self's MP4.
            download_url = await _build_playback_url(job)
            return _to_response(job, download_url=download_url)

        download_url = await _build_playback_url(leaf)
        return _to_response(
            job,
            download_url=download_url,
            effective_render_job_id=cast(UUID, leaf.id),
        )
    
    async def get_render_job_orm(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ):
        """Return the ORM row (or None) — used by callers that need
        fields not exposed in RenderJobResponse (e.g., input_spec).
        """
        return await self.repository.get_by_id_for_user(
            org_id, user_id, job_id,
        )

    async def update_render_job_title(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
        title: str | None,
    ) -> RenderJobResponse:
        """Update the user-facing title on a render job.

        Scoped to org + user so cross-user renaming is impossible.
        Raises 404 when the job is missing or owned by someone else
        — same surface as ``get_render_job`` so the FE doesn't have
        to special-case "not yours" vs "doesn't exist".

        ``download_url`` is populated for completed jobs so the
        response shape matches ``get_render_job`` and the FE can
        slot the result in without re-fetching.
        """
        job = await self.repository.update_title(org_id, user_id, job_id, title)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        download_url = await _build_playback_url(job)
        return _to_response(job, download_url=download_url)

    async def rerender_from_edits(
        self,
        org_id: UUID,
        user_id: UUID,
        parent_job_id: UUID,
    ) -> RenderJobResponse:
        """Promote a parent render's current ``input_spec`` to a fresh
        queued render.

        Call site: the operator's "Render with my edits" button, after
        they've used PATCH ``/subtitles`` (debounced auto-save) to
        update ``parent.input_spec.subtitles``.

        The child render carries the parent's current ``input_spec``
        (which already has the edited subtitles), gets its own
        ``id``, points back at the parent via
        ``refined_from_render_job_id``, and inherits
        ``refinement_source`` (typically ``'manual_edit'`` set by
        the prior PATCH).

        The parent's ``replaced_by_render_job_id`` is set to the new
        child so ``useRefinedRenderChain`` follows the swap.

        Idempotent within a 30s window via composition-hash dedupe —
        repeated clicks within 30s return the existing child rather
        than creating duplicates.

        Errors:
          - 404: parent missing or owned by a different (org_id, user_id).
          - 409: parent isn't in 'completed' state (rerendering an
                 in-flight job has unclear semantics — wait first).
        """
        parent = await self.repository.get_by_id(org_id, user_id, parent_job_id)
        if parent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )
        if parent.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot rerender from a {parent.status!r} job — "
                    "wait for the original render to complete first."
                ),
            )

        # Hash the parent's CURRENT input_spec (post-edits). The
        # parent's stored composition_hash column reflects its
        # creation-time spec, which is now stale; recompute.
        composition_hash = compute_composition_hash(parent.input_spec)

        # Composition-hash dedupe — repeated clicks within 30s collapse
        # to the existing child. Skip the parent itself in case its
        # own hash happens to match (it shouldn't post-edit, but a
        # no-op rerender of an unedited refined child could match).
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=_DEDUPE_WINDOW_SECONDS
        )
        existing = await self.repository.find_recent_duplicate(
            org_id=org_id,
            user_id=user_id,
            composition_hash=composition_hash,
            since=cutoff,
        )
        if existing is not None and existing.id != parent.id:
            logger.info(
                "rerender_idempotent_replay",
                parent_id=str(parent_job_id),
                child_id=str(existing.id),
                org_id=str(org_id),
                user_id=str(user_id),
                composition_hash=composition_hash,
            )
            download_url = await _build_playback_url(existing)
            return _to_response(existing, download_url=download_url)

        child = await self.repository.create_rerender_child(
            org_id=org_id,
            user_id=user_id,
            parent_job_id=parent_job_id,
            composition_hash=composition_hash,
        )
        if child is None:
            # Parent vanished or changed state between the get_by_id
            # check and the create. Treat as a 404 — race-safe and
            # consistent with get_render_job semantics.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        # Link parent → child unless overlay mode is on. In overlay
        # mode the parent stays canonical (the operator's editable
        # working canvas with subs in input_spec); the export child
        # is a download artifact only. Setting ``replaced_by`` would
        # point future chain walks at a stale snapshot and break the
        # editor's cue source. The export child still carries
        # ``refined_from_render_job_id=parent.id`` (set by
        # ``create_rerender_child``) — that's what the post_render
        # hook's ``_check_guards`` reads to skip Whisper recursion on
        # the export child.
        # In OFF mode (legacy Whisper-refined-child flow) the link is
        # how ``useRefinedRenderChain`` finds the canonical render —
        # MUST stay set.
        from app.modules.shorts_render import refinement_repository

        overlay_mode = (
            get_settings().auto_shorts_product_v2_overlay_mode_enabled
        )
        if not overlay_mode:
            await refinement_repository.link_parent_to_child(
                self.repository.session,
                parent_id=parent_job_id,
                child_id=cast(UUID, child.id),
            )
        else:
            logger.info(
                "rerender_export_link_skipped",
                parent_id=str(parent_job_id),
                child_id=str(child.id),
                org_id=str(org_id),
                user_id=str(user_id),
            )

        logger.info(
            "rerender_from_edits_created",
            parent_id=str(parent_job_id),
            child_id=str(child.id),
            org_id=str(org_id),
            user_id=str(user_id),
            composition_hash=composition_hash,
        )

        # Commit before SQS publish — same pattern as create_render_job
        # to avoid the 2026-05-06 stranded-render race.
        await self.repository.session.commit()

        try:
            from app.sqs_producer import publish_shorts_render_job

            publish_shorts_render_job(
                job_id=cast(UUID, child.id),
                org_id=org_id,
                video_id=child.video_id,
                input_spec=child.input_spec,
            )
        except Exception:
            logger.exception(
                "rerender_sqs_publish_failed",
                parent_id=str(parent_job_id),
                child_id=str(child.id),
            )
            await self.repository.update_status(
                cast(UUID, child.id),
                "failed",
                error="Failed to enqueue rerender",
            )
            await self.repository.session.commit()
            child.status = "failed"
            child.error = "Failed to enqueue rerender"

        return _to_response(child)

    async def update_render_job_subtitles(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
        subtitles: list[Any],
    ) -> RenderJobResponse:
        """Replace the job's subtitles and mark it as manually edited.

        ``subtitles`` is a list of validated ``SubtitleSpec`` instances
        from the router (Pydantic does the per-item validation). The
        repository accepts plain dicts so it stays free of contract
        package imports — we serialize via ``model_dump`` here.

        Side effect: ``refinement_source`` flips to ``'manual_edit'``,
        which the post-render Whisper hook checks via
        :func:`refinement_service._check_guards` to skip Whisper
        passes on operator-edited subtitles.

        Scoped to org+user; raises 404 when the job doesn't exist or
        isn't owned. Idempotent: repeated calls with the same
        subtitles produce the same row state.
        """
        # Each ``SubtitleSpec`` has ``.model_dump()``; we duck-type
        # rather than import the contract package to keep the
        # service layer thin.
        subtitle_dicts = [s.model_dump() for s in subtitles]
        job = await self.repository.update_subtitles_with_manual_edit(
            org_id, user_id, job_id, subtitle_dicts
        )
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        download_url = await _build_playback_url(job)
        return _to_response(job, download_url=download_url)

    async def list_render_jobs(
        self,
        org_id: UUID,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> RenderJobListResponse:
        """List render jobs for a user with pagination."""
        jobs, total = await self.repository.list_by_user(org_id, user_id, limit, offset)
        return RenderJobListResponse(
            items=[_to_response(job) for job in jobs],
            total=total,
        )

    async def delete_render_job(
        self,
        org_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> None:
        """Delete a render job. Cleans up S3 output if present.

        Scoped to org + user — matches get_render_job semantics.
        """
        job = await self.repository.get_by_id(org_id, user_id, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Render job not found",
            )

        # Clean up S3 output if it exists
        if job.output_s3_key:
            try:
                from app.storage.s3 import S3Client

                settings = get_settings()
                s3 = S3Client(bucket=settings.drive_s3_bucket)
                s3.delete(job.output_s3_key)
            except Exception:
                logger.exception(
                    "s3_render_output_delete_failed",
                    job_id=str(job_id),
                    s3_key=job.output_s3_key,
                )

        await self.repository.delete(org_id, user_id, job_id)

    async def _validate_scene_clips(
        self,
        org_id: UUID,
        payload: RenderJobCreate,
    ) -> None:
        """Validate that all scene clips fall within their scene boundaries."""
        clips = payload.composition.scene_clips

        # Build composite doc IDs matching OpenSearch pattern
        doc_ids = [f"{org_id}:{clip.scene_id}" for clip in clips]

        # Batch-fetch all scenes from OpenSearch
        scenes = await self.scene_search.mget_scenes(doc_ids)

        for i, clip in enumerate(clips):
            doc_id = f"{org_id}:{clip.scene_id}"
            scene = scenes.get(doc_id)

            if scene is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"scene_clip[{i}]: scene '{clip.scene_id}' not found",
                )

            scene_start = scene.get("start_ms", 0)
            scene_end = scene.get("end_ms", 0)

            if clip.start_ms < scene_start:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"scene_clip[{i}]: start_ms out of scene bounds "
                        f"(clip: {clip.start_ms}-{clip.end_ms}, "
                        f"scene: {scene_start}-{scene_end})"
                    ),
                )

            if clip.end_ms > scene_end:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"scene_clip[{i}]: end_ms out of scene bounds "
                        f"(clip: {clip.start_ms}-{clip.end_ms}, "
                        f"scene: {scene_start}-{scene_end})"
                    ),
                )
