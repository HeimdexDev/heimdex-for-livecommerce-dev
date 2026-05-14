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


@dataclass(frozen=True)
class SummaryResult:
    render_job_id: UUID
    summary: str
    prompt_version: str
    model: str
    cost_usd: float
    generated_at: datetime


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

        # 1. Extract source video_id + time windows from input_spec
        spec = render_job.input_spec or {}
        scene_clips = spec.get("scene_clips") or []
        if not scene_clips:
            raise SummaryUnavailableError("input_spec.scene_clips empty")

        # All clips share the same video_id for shorts_auto_product
        # output (single-source clip selector). Take the first.
        source_video_id = scene_clips[0].get("video_id") or render_job.video_id
        windows = [
            (int(c["source_start_ms"]), int(c["source_end_ms"]))
            for c in scene_clips
            if c.get("source_start_ms") is not None
            and c.get("source_end_ms") is not None
        ]
        total_duration_ms = sum(end - start for start, end in windows)

        # 2. Fetch all scenes of the source video, filter to windows
        scenes_doc = await self.os_client.get_video_scenes(
            org_id=str(org_id),
            video_id=source_video_id,
            page_size=200,  # generous cap; full-video scene count is bounded
        )
        all_scenes = scenes_doc.get("scenes") or scenes_doc.get("results") or []
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
        )


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