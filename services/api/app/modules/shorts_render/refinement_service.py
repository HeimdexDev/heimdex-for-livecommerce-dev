"""Post-render Whisper subtitle refinement orchestration.

The full pipeline that fires after a render's worker callback flips
the row to ``completed``:

  1. Acquire row lock with ``SKIP LOCKED`` (so two concurrent
     callbacks can't both pass guards).
  2. Run guards: parent has output, isn't already refined, isn't a
     refined child, and has subtitles to refine.
  3. Download the rendered MP4 from S3 (timeout-bounded).
  4. Call OpenAI Whisper for word-level timestamps.
  5. Re-chunk Whisper words into a fresh subtitle list with
     :func:`app.lib.subtitle_chunking.chunk_words`.
  6. Build a refined ``CompositionSpec`` (everything from parent's
     spec, only ``subtitles[]`` swapped).
  7. Insert child render row + link parent → child.
  8. Publish the child to SQS for the worker to render.

**Error contract**: this module's coroutine NEVER raises out to the
hook caller. Every failure path logs and returns. The original
render stays canonical; refinement just doesn't happen for that
job. Operators can manually trigger a re-render later.

**Coupling rules**:
- Imports from ``app.lib.*`` and ``app.modules.shorts_render.*``
  only.
- Does **NOT** import ``app.modules.shorts_auto_product`` — the
  refinement service is feature-agnostic and works for any
  composition with subtitles, not just auto-shorts output.
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.lib.subtitle_chunking import Subtitle, chunk_words
from app.lib.whisper_transcribe import (
    BudgetExceededError,
    InMemoryBudgetTracker,
    WhisperResult,
    WhisperRetryableError,
    WhisperTerminalError,
    WhisperTranscriber,
)
from app.logging_config import get_logger

# Use structlog so structured kwargs (parent_job_id, child_id, cost,
# latency, etc.) reach the JSON formatter. See the matching note in
# ``post_render_hook.py``.
logger = get_logger(__name__)


# Module-level strong-ref set to keep fire-and-forget tasks from being
# garbage-collected mid-flight. Same pattern as
# ``image_caption/service.py:53`` and
# ``shorts_auto_product/enumerate_stt/service.py:62``.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


# Lazy-initialized singletons. Constructed on first use so unit tests
# that don't touch refinement don't pay for OpenAI client setup.
_TRANSCRIBER: WhisperTranscriber | None = None
_BUDGET: InMemoryBudgetTracker | None = None


def _get_budget_tracker() -> InMemoryBudgetTracker:
    global _BUDGET
    if _BUDGET is None:
        settings = get_settings()
        _BUDGET = InMemoryBudgetTracker(
            daily_budget_usd=(
                settings.auto_shorts_product_v2_whisper_daily_budget_usd
            ),
        )
    return _BUDGET


def _get_transcriber() -> WhisperTranscriber | None:
    """Lazy-construct. Returns None if no API key (treated as kill switch)."""
    global _TRANSCRIBER
    if _TRANSCRIBER is not None:
        return _TRANSCRIBER
    settings = get_settings()
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        logger.warning(
            "whisper_refine_disabled_no_api_key",
            **{"reason": "OPENAI_API_KEY missing or empty"},
        )
        return None
    _TRANSCRIBER = WhisperTranscriber(
        api_key=api_key,
        budget_tracker=_get_budget_tracker(),
        model=settings.auto_shorts_product_v2_whisper_model,
        timeout_s=settings.auto_shorts_product_v2_whisper_timeout_s,
    )
    return _TRANSCRIBER


def reset_singletons_for_tests() -> None:
    """Clear lazy singletons. Test-only — NOT for production paths."""
    global _TRANSCRIBER, _BUDGET
    _TRANSCRIBER = None
    _BUDGET = None


def schedule_refinement(parent_job_id: UUID) -> None:
    """Fire-and-forget scheduler. Returns immediately.

    The caller (post_render_hook) has already verified the master
    flag + rollout bucket. This function does NOT re-check those —
    it just owns the asyncio.create_task plumbing.

    Strong-ref to the task is held in ``_BACKGROUND_TASKS`` to keep
    it from being GC'd before completion.
    """
    task = asyncio.create_task(_runner(parent_job_id))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _runner(parent_job_id: UUID) -> None:
    """The whole pipeline. Never raises out."""
    try:
        await _run_refinement(parent_job_id)
    except Exception:
        # Defensive: any uncaught exception is a bug in the
        # orchestration; surface it but never propagate to the
        # task-scheduler caller.
        logger.exception(
            "whisper_refine_unexpected_error",
            **{"parent_job_id": str(parent_job_id)},
        )


# Importing inside the function avoids a circular import:
# refinement_service is imported by post_render_hook which is
# imported by internal_router during FastAPI route registration,
# and the DB base module pulls in models that depend on the metadata
# being loaded.
async def _run_refinement(parent_job_id: UUID) -> None:
    from app.db.base import get_async_session_factory
    from app.modules.shorts_render import refinement_repository
    from app.modules.shorts_render.models import ShortsRenderJob
    from app.storage.s3 import S3Client

    settings = get_settings()
    started_at = time.monotonic()

    transcriber = _get_transcriber()
    if transcriber is None:
        logger.info(
            "whisper_refine_skipped_no_transcriber",
            **{"parent_job_id": str(parent_job_id)},
        )
        return

    session_factory = get_async_session_factory()
    async with session_factory() as session:
        # ---- 1. Lock parent + run guards ----
        parent = await refinement_repository.lock_parent_or_none(
            session, parent_job_id
        )
        if parent is None:
            # Either deleted or locked elsewhere; another runner
            # owns it (or did already). Bail silently.
            logger.info(
                "whisper_refine_skipped_locked_or_missing",
                **{"parent_job_id": str(parent_job_id)},
            )
            return

        skip_reason = _check_guards(parent)
        if skip_reason is not None:
            logger.info(
                "whisper_refine_skipped",
                **{
                    "parent_job_id": str(parent_job_id),
                    "reason": skip_reason,
                },
            )
            await session.rollback()  # release the lock
            return

        # Capture parent fields BEFORE leaving the session scope —
        # we'll need them for the S3 download + Whisper prompt
        # without re-querying.
        parent_input_spec: dict[str, Any] = dict(parent.input_spec or {})
        parent_output_s3_key: str = parent.output_s3_key  # type: ignore[assignment]
        parent_output_duration_ms: int | None = parent.output_duration_ms

        # ---- 2. S3 download (outside the lock; download is slow) ----
        await session.rollback()  # release lock; we'll re-query later

    # We're now outside the session context. Download MP4.
    s3 = S3Client(bucket=settings.drive_s3_bucket)
    try:
        audio_bytes = await asyncio.wait_for(
            s3.get_object_bytes_async(parent_output_s3_key),
            timeout=settings.auto_shorts_product_v2_whisper_s3_download_timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "whisper_refine_s3_download_timeout",
            **{
                "parent_job_id": str(parent_job_id),
                "s3_key": parent_output_s3_key,
            },
        )
        return
    except Exception:
        logger.exception(
            "whisper_refine_s3_download_failed",
            **{
                "parent_job_id": str(parent_job_id),
                "s3_key": parent_output_s3_key,
            },
        )
        return

    if not audio_bytes:
        logger.warning(
            "whisper_refine_s3_object_missing",
            **{
                "parent_job_id": str(parent_job_id),
                "s3_key": parent_output_s3_key,
            },
        )
        return

    # ---- 3. Whisper transcription ----
    duration_seconds = (parent_output_duration_ms or 60_000) / 1000.0
    prompt = _build_prompt_from_spec(parent_input_spec)
    try:
        result = await transcriber.transcribe(
            audio_bytes=audio_bytes,
            audio_duration_seconds=duration_seconds,
            language=settings.auto_shorts_product_v2_whisper_language,
            prompt=prompt,
        )
    except BudgetExceededError:
        logger.info(
            "whisper_refine_skipped_budget",
            **{"parent_job_id": str(parent_job_id)},
        )
        return
    except (WhisperTerminalError, WhisperRetryableError):
        logger.warning(
            "whisper_refine_transcription_failed",
            **{"parent_job_id": str(parent_job_id)},
            exc_info=True,
        )
        return
    except Exception:
        logger.exception(
            "whisper_refine_transcription_unexpected",
            **{"parent_job_id": str(parent_job_id)},
        )
        return

    if not result.words:
        logger.info(
            "whisper_refine_skipped_empty_words",
            **{
                "parent_job_id": str(parent_job_id),
                "language": result.language,
                "duration_seconds": result.duration_seconds,
            },
        )
        return

    # ---- 4. Re-chunk + validate ----
    timeline_clamp_ms = _extract_timeline_duration_ms(parent_input_spec)
    new_subtitles = chunk_words(
        result.words,
        timeline_clamp_ms=timeline_clamp_ms,
    )
    if not new_subtitles:
        logger.warning(
            "whisper_refine_skipped_no_chunks",
            **{
                "parent_job_id": str(parent_job_id),
                "word_count": len(result.words),
            },
        )
        return

    # ---- 5. Build refined CompositionSpec dict ----
    try:
        refined_spec = _build_refined_input_spec(
            parent_input_spec, new_subtitles
        )
    except (KeyError, ValueError, TypeError):
        logger.exception(
            "whisper_refine_spec_build_failed",
            **{"parent_job_id": str(parent_job_id)},
        )
        return

    # ---- 6. Re-acquire session, create child, link, publish ----
    async with session_factory() as session:
        # Re-lock parent. By now another runner may have already
        # refined it (raced through guards while we were on Whisper).
        parent = await refinement_repository.lock_parent_or_none(
            session, parent_job_id
        )
        if parent is None or parent.replaced_by_render_job_id is not None:
            logger.info(
                "whisper_refine_skipped_raced",
                **{"parent_job_id": str(parent_job_id)},
            )
            return

        try:
            child: ShortsRenderJob = await refinement_repository.create_refined_child(
                session,
                parent=parent,
                refined_input_spec=refined_spec,
            )
            await refinement_repository.link_parent_to_child(
                session,
                parent_id=parent_job_id,
                child_id=child.id,  # type: ignore[arg-type]
            )
            await session.commit()
        except Exception:
            logger.exception(
                "whisper_refine_db_write_failed",
                **{"parent_job_id": str(parent_job_id)},
            )
            await session.rollback()
            return

        child_id = child.id
        child_org_id = child.org_id
        child_video_id = child.video_id

    # ---- 7. SQS publish (after commit; matches existing pattern) ----
    try:
        from app.sqs_producer import publish_shorts_render_job

        publish_shorts_render_job(
            job_id=child_id,  # type: ignore[arg-type]
            org_id=child_org_id,  # type: ignore[arg-type]
            video_id=child_video_id,
            input_spec=refined_spec,
        )
    except Exception:
        logger.exception(
            "whisper_refine_sqs_publish_failed",
            **{
                "parent_job_id": str(parent_job_id),
                "child_id": str(child_id),
            },
        )
        # Mark the child as failed so it doesn't sit queued forever.
        async with session_factory() as session:
            from app.modules.shorts_render.repository import (
                ShortsRenderJobRepository,
            )

            repo = ShortsRenderJobRepository(session)
            await repo.update_status(
                child_id,  # type: ignore[arg-type]
                "failed",
                error="Failed to enqueue refined render",
            )
            await session.commit()
        return

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    logger.info(
        "whisper_refine_completed",
        **{
            "parent_job_id": str(parent_job_id),
            "child_id": str(child_id),
            "word_count": len(result.words),
            "subtitle_count_before": len(parent_input_spec.get("subtitles", [])),
            "subtitle_count_after": len(new_subtitles),
            "whisper_cost_usd": result.cost_usd,
            "whisper_latency_ms": result.latency_ms,
            "total_elapsed_ms": elapsed_ms,
        },
    )


def _check_guards(parent: Any) -> str | None:
    """Return a skip reason string, or None to proceed.

    Guards (any one short-circuits):
      - ``manual_edit``: operator hand-edited subtitles; do not overwrite.
      - ``already_refined``: forward pointer set; refinement already happened.
      - ``refined_from``: this row IS a refined child; don't recurse.
      - ``no_output_s3_key``: render never produced an MP4 to transcribe.
      - ``no_subtitles``: parent had no subtitles to refine; nothing to swap.
    """
    if parent.refinement_source == "manual_edit":
        return "manual_edit"
    if parent.replaced_by_render_job_id is not None:
        return "already_refined"
    if parent.refined_from_render_job_id is not None:
        return "refined_from"
    if not parent.output_s3_key:
        return "no_output_s3_key"
    spec = parent.input_spec or {}
    if not spec.get("subtitles"):
        return "no_subtitles"
    return None


def _build_prompt_from_spec(spec: dict[str, Any]) -> str | None:
    """Extract product names from composition title for Whisper bias.

    Whisper's ``prompt`` parameter biases the model toward specific
    spellings — particularly useful for Korean brand names that the
    base model may transliterate inconsistently. We pull from the
    spec's ``title`` (typically a product name in auto-shorts) and
    cap at 224 tokens (Whisper's hard limit).

    Returns ``None`` when there's nothing useful to bias on.
    """
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    return title.strip()[:600]  # ~224 token approximation


def _extract_timeline_duration_ms(spec: dict[str, Any]) -> int | None:
    """Compute total timeline duration from clip spans.

    Used as ``timeline_clamp_ms`` so chunked subtitles don't extend
    past the rendered video's end. Returns None when the spec lacks
    clips (caller should treat as unbounded).
    """
    clips = spec.get("scene_clips") or []
    if not clips:
        return None
    try:
        ends = [int(c.get("timeline_end_ms", 0)) for c in clips]
    except (TypeError, ValueError):
        return None
    return max(ends, default=None) or None


def _build_refined_input_spec(
    parent_spec: dict[str, Any],
    new_subtitles: list[Subtitle],
) -> dict[str, Any]:
    """Build a refined ``CompositionSpec`` JSON dict.

    Preserves every parent field except ``subtitles[]``, which is
    replaced with the chunker output.

    Style + template_id resolution:

    1. If the parent carries any subtitles, inherit ``style`` and
       ``template_id`` from the first one (callers use uniform
       style for the whole render — historically that's been the
       contract).
    2. Else (parent has empty subtitles — the post-2026-05-07
       auto-shorts default), fall back to the auto-shorts pill
       style sized to the parent's output canvas. Without this
       fallback, Whisper-only auto-shorts renders would lose the
       white pill + black text the operator-target screenshot
       requires.

    Cue text is also passed through ``wrap_korean_subtitle_lines``
    so multi-line wrapping stays consistent with the pre-render
    composition_builder rules — same chars-per-line budget,
    same 2-line cap.

    Returns a plain dict (no Pydantic round-trip) — the caller
    stores it in JSONB. The render worker re-validates against
    ``CompositionSpec`` on receipt, so any malformed output is
    surfaced loudly there.
    """
    from app.modules.shorts_auto_product.subtitle_layout import (
        DEFAULT_CANVAS_HEIGHT,
        DEFAULT_CANVAS_WIDTH,
        build_auto_shorts_subtitle_style,
        compute_chars_per_line,
        wrap_korean_subtitle_lines,
    )

    refined = dict(parent_spec)
    parent_subs = parent_spec.get("subtitles") or []
    style_template: dict[str, Any] | None = None
    template_id: str | None = None
    if parent_subs:
        first = parent_subs[0]
        if isinstance(first, dict):
            style_template = first.get("style")
            tid = first.get("template_id")
            if isinstance(tid, str):
                template_id = tid

    # Fallback to auto-shorts pill when the parent shipped without
    # any subtitle template (the new caption-source default for
    # auto-shorts). Sized to the parent's actual canvas so the same
    # pill scales with future resolution bumps.
    output_dims = parent_spec.get("output") if isinstance(parent_spec, dict) else None
    canvas_height = (
        int(output_dims["height"])
        if isinstance(output_dims, dict)
        and isinstance(output_dims.get("height"), (int, float))
        else DEFAULT_CANVAS_HEIGHT
    )
    canvas_width = (
        int(output_dims["width"])
        if isinstance(output_dims, dict)
        and isinstance(output_dims.get("width"), (int, float))
        else DEFAULT_CANVAS_WIDTH
    )
    if style_template is None:
        fallback_style = build_auto_shorts_subtitle_style(
            canvas_height=canvas_height,
        )
        style_template = fallback_style.model_dump()

    # Always compute the wrap budget from the resolved style — works
    # whether the style came from the parent or the fallback.
    chars_per_line = compute_chars_per_line(
        canvas_width=canvas_width,
        font_size_px=int(style_template.get("font_size_px") or 32),
        padding=int(style_template.get("background_padding") or 11),
    )

    refined_subs: list[dict[str, Any]] = []
    for sub in new_subtitles:
        if sub.end_ms <= sub.start_ms:
            continue  # SubtitleSpec validator rejects end <= start
        wrapped_text = wrap_korean_subtitle_lines(
            sub.text, chars_per_line=chars_per_line,
        )
        item: dict[str, Any] = {
            "text": wrapped_text,
            "start_ms": sub.start_ms,
            "end_ms": sub.end_ms,
            "style": dict(style_template),
        }
        if template_id is not None:
            item["template_id"] = template_id
        refined_subs.append(item)

    refined["subtitles"] = refined_subs
    return refined
