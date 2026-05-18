"""ShortsRenderSummaryService — generate a 1-2 sentence Korean summary
for a completed shorts render.

Reuses existing signals from the source video's scenes (Whisper STT,
PaddleOCR, VLM scene_caption, speaker transcript) — NO frame extraction,
NO video file upload. Pure text-only gpt-4o-mini call.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from app.modules.shorts_render.summary_prompt import (
    PROMPT_VERSION,
    _SYSTEM_PROMPT,
    _SceneSignals,
    build_user_prompt,
)

logger = logging.getLogger(__name__)


_MODEL_PRICING_USD_PER_M = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


class SummaryError(Exception):
    """Base for summary service errors."""


class SummaryNotReadyError(SummaryError):
    """Render job not completed yet."""


class SummaryUnavailableError(SummaryError):
    """No usable scene signals were found for the clip."""


# Defensive cap on the source-video scene pagination. Korean
# livecommerce VODs run ~500 scenes at the high end (observed max on
# staging: 525); 5000 leaves 10x headroom without risking a runaway
# fetch on a malformed video_id.
_SCENE_FETCH_CAP = 5000
_SCENE_PAGE_SIZE = 200


@dataclass(frozen=True)
class SummaryResult:
    render_job_id: UUID
    summary: str
    prompt_version: str
    model: str
    cost_usd: float
    generated_at: datetime
    # True when the summary came from the persisted column rather than
    # a fresh OpenAI call. The router uses this to skip the DB write
    # on a cache hit (and to know the call cost nothing).
    from_cache: bool = False


@dataclass
class ShortsRenderSummaryService:
    """Generates summary for a completed render job.

    Stateless except for injected dependencies.
    """
    openai_client: AsyncOpenAI
    os_client: Any  # SceneSearchClient
    model: str
    timeout_s: float
    prompt_version: str

    async def generate(
        self,
        *,
        org_id: UUID,
        render_job: Any,  # ShortsRenderJob
        max_sentences: int = 2,
    ) -> SummaryResult:
        if render_job.status != "completed":
            raise SummaryNotReadyError(
                f"render_job {render_job.id} status={render_job.status}"
            )

        # 0. Cache hit — a summary already persisted for the CURRENT
        # prompt version. Return it without an OpenAI call. A
        # prompt-version bump (or a NULL version on a legacy row)
        # falls through to regeneration; ``max_sentences`` is NOT part
        # of the cache key (the persisted summary is the canonical one
        # regardless of what length a re-request asks for — callers
        # wanting a different length re-trigger explicitly and the
        # router overwrites the column).
        cached = (getattr(render_job, "summary", None) or "").strip()
        cached_version = getattr(render_job, "summary_prompt_version", None)
        if cached and cached_version == self.prompt_version:
            logger.info(
                "shorts_summary_cache_hit",
                extra={
                    "render_job_id": str(render_job.id),
                    "prompt_version": cached_version,
                },
            )
            return SummaryResult(
                render_job_id=render_job.id,
                summary=cached,
                prompt_version=cached_version,
                model=self.model,
                cost_usd=0.0,
                generated_at=(
                    getattr(render_job, "summary_generated_at", None)
                    or datetime.now(timezone.utc)
                ),
                from_cache=True,
            )

        # 1. Extract source video_id + time windows from input_spec
        spec = render_job.input_spec or {}
        scene_clips = spec.get("scene_clips") or []
        if not scene_clips:
            raise SummaryUnavailableError("input_spec.scene_clips empty")

        # All clips share the same video_id for shorts_auto_product
        # output (single-source clip selector). Take the first.
        source_video_id = scene_clips[0].get("video_id") or render_job.video_id
        windows = [
            (int(c["start_ms"]), int(c["end_ms"]))
            for c in scene_clips
            if c.get("start_ms") is not None
            and c.get("end_ms") is not None
        ]
        total_duration_ms = sum(end - start for start, end in windows)

        # 2. Fetch ALL scenes of the source video, filter to windows.
        # Must paginate — a clip can be sourced from late in an
        # 80-minute VOD, and a single capped page would silently
        # truncate those scenes, producing a summary off the wrong
        # (or empty) signal set.
        all_scenes = await _fetch_all_video_scenes(
            self.os_client, org_id=org_id, video_id=source_video_id
        )
        scenes_in_clip = _filter_scenes_by_windows(all_scenes, windows)
        if not scenes_in_clip:
            raise SummaryUnavailableError(
                f"no scenes intersect render windows for video {source_video_id}"
            )

        # 3. Build text-only prompt
        scene_signals = [
            _SceneSignals(
                start_ms=int(s.get("start_ms") or 0),
                end_ms=int(s.get("end_ms") or 0),
                transcript=str(s.get("transcript_raw") or ""),
                scene_caption=str(s.get("scene_caption") or ""),
                ocr_text=str(s.get("ocr_text_raw") or ""),
                speaker_transcript=str(s.get("speaker_transcript") or ""),
            )
            for s in scenes_in_clip
        ]
        user_prompt = build_user_prompt(
            scenes=scene_signals,
            target_duration_ms=total_duration_ms,
            max_sentences=max_sentences,
        )

        # 4. OpenAI text-only call
        try:
            response = await asyncio.wait_for(
                self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                ),
                timeout=self.timeout_s,
            )
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "shorts_summary_llm_failed",
                extra={
                    "render_job_id": str(render_job.id),
                    "error_class": type(exc).__name__,
                    "error": str(exc)[:300],
                },
            )
            raise SummaryError(f"openai call failed: {exc}") from exc

        summary_text = (response.choices[0].message.content or "").strip()
        if not summary_text:
            raise SummaryError("openai returned empty content")

        cost = _cost_from_usage(response, self.model)
        logger.info(
            "shorts_summary_generated",
            extra={
                "render_job_id": str(render_job.id),
                "model": self.model,
                "prompt_version": self.prompt_version,
                "cost_usd": cost,
                "summary_chars": len(summary_text),
            },
        )

        return SummaryResult(
            render_job_id=render_job.id,
            summary=summary_text,
            prompt_version=self.prompt_version,
            model=self.model,
            cost_usd=cost,
            generated_at=datetime.now(timezone.utc),
            from_cache=False,
        )


async def _fetch_all_video_scenes(
    os_client: Any,
    *,
    org_id: UUID,
    video_id: str,
) -> list[dict[str, Any]]:
    """Page through every scene of a source video.

    ``get_video_scenes`` is page-capped; a clip sourced from late in a
    long VOD would be missed by a single page. Loop on ``offset``
    until a short page (or the defensive ``_SCENE_FETCH_CAP``).
    """
    out: list[dict[str, Any]] = []
    offset = 0
    while offset < _SCENE_FETCH_CAP:
        doc = await os_client.get_video_scenes(
            org_id=str(org_id),
            video_id=video_id,
            page_size=_SCENE_PAGE_SIZE,
            offset=offset,
        )
        batch = doc.get("scenes") or doc.get("results") or []
        if not batch:
            break
        out.extend(batch)
        if len(batch) < _SCENE_PAGE_SIZE:
            break
        offset += len(batch)
    return out


def _filter_scenes_by_windows(
    scenes: list[dict[str, Any]],
    windows: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    """Keep scenes whose [start_ms, end_ms] overlaps any window."""
    if not windows:
        return []
    out: list[dict[str, Any]] = []
    for s in scenes:
        s_start = int(s.get("start_ms") or 0)
        s_end = int(s.get("end_ms") or 0)
        for w_start, w_end in windows:
            if s_start < w_end and s_end > w_start:
                out.append(s)
                break
    return sorted(out, key=lambda x: int(x.get("start_ms") or 0))


def _cost_from_usage(response: Any, model: str) -> float:
    pricing = _MODEL_PRICING_USD_PER_M.get(model)
    if pricing is None:
        return 0.0
    try:
        usage = response.usage
        in_cost = (usage.prompt_tokens / 1_000_000.0) * pricing["input"]
        out_cost = (usage.completion_tokens / 1_000_000.0) * pricing["output"]
        return in_cost + out_cost
    except (AttributeError, TypeError):
        return 0.0


__all__ = [
    "ShortsRenderSummaryService",
    "SummaryResult",
    "SummaryError",
    "SummaryNotReadyError",
    "SummaryUnavailableError",
]