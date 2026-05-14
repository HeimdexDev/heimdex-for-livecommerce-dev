"""Chunk scoring — port of standalone product-auto-shorts'
``scoring.py::GPTChunkScorer`` + ``score_segment``.

Splits each :class:`MentionSegment` into 10-30s chunks (text from the
underlying ``MentionedScene[]``), asks gpt-4o-mini for hook/CTA/
importance scores, returns :class:`ScoredChunk[]`. Service-level
fallback to a heuristic scorer on any LLM defect (timeout, JSON
parse, schema validation, budget exhausted) — the heuristic gives a
deterministic 0.5 baseline so the pipeline always produces output.

Distinct from ``app.modules.shorts_auto.scorers.llm.OpenAILLMScorer``
in two ways:

1. **Different operation.** That scorer is a *scene picker* (gpt-4o
   asked "which whole scenes belong in the shorts clip"); this one is
   a *chunk scorer* (asked "score this 10-30s window for hook/CTA/
   importance"). Different prompts, different response schemas.
2. **Loose-coupling.** ``shorts_auto_product`` cannot import from
   ``app.modules.shorts_auto.*`` per CLAUDE.md. This module is
   self-contained and reuses only ``heimdex_media_contracts`` (zero)
   + ``openai`` + own-module errors/models.

Cost model (gpt-4o-mini):

* Input: ~600 system tokens + ~1k chunk-text-and-context per call,
  batched up to 20 chunks per request → ~$0.0003 per chunk
* Output: ~50 tokens per chunk → trivial
* **Total: ~$0.005 for a 60s clip selection** (15 chunks). The
  per-scan budget bucket
  ``auto_shorts_product_v2_daily_budget_usd=50.0`` swallows this
  comfortably.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionSegment,
    ScoredChunk,
)

logger = logging.getLogger(__name__)


# Chunk size bounds — match the standalone repo. The cap is
# ``min(30s, max(10s, requested))`` so the scorer never gets handed
# a chunk shorter than 10s (too little speech to score) or longer
# than 30s (LLM context bloat + quality drop).
_CHUNK_MIN_MS = 10_000
_CHUNK_MAX_MS = 30_000

# Maximum chunks per single LLM call. Standalone uses 20; we mirror.
# Beyond ~20 the model's accuracy on per-chunk scoring degrades.
_MAX_CHUNKS_PER_REQUEST = 20

# Heuristic baseline for the fallback scorer. 0.5 / False / 0.5 is
# deliberate: the clip selector treats it as "neutral, no signal"
# — chunks survive selection only if no LLM-scored chunks exist.
_HEURISTIC_HOOK = 0.5
_HEURISTIC_HAS_CTA = False
_HEURISTIC_IMPORTANCE = 0.5


# ---------- LLM contract ----------
#
# The system prompt is mirrored verbatim from
# ``product-auto-shorts/app/services/scoring.py::SYSTEM_PROMPT`` —
# we don't have a calibration story to deviate yet, and the
# standalone repo's prompt has been tuned on real Korean livecommerce
# transcripts. Worth a contracts-side prompt class once we run the
# eval harness in PR 3.
_SYSTEM_PROMPT = (
    "You score live commerce transcript chunks for short-form clip "
    "selection.\n"
    "\n"
    "For each chunk, detect:\n"
    "- excitement level\n"
    "- urgency\n"
    "- sales language\n"
    "- emotional impact\n"
    "- whether the chunk is genuinely about the PRIMARY catalog "
    "vs OTHER selected catalogs\n"
    "\n"
    "Return strict JSON through the provided tool with exactly one "
    "score object per input chunk, in the same order.\n"
    "\n"
    "Schema for each score:\n"
    "{\n"
    "  \"hook_score\": float between 0 and 1,\n"
    "  \"has_cta\": boolean,\n"
    "  \"importance_score\": float between 0 and 1,\n"
    "  \"primary_catalog_match\": float between 0 and 1\n"
    "}\n"
    "\n"
    "Scoring guidance:\n"
    "- hook_score: opening strength, attention value, emotional "
    "  pull, surprise, or curiosity.\n"
    "- has_cta: true only when the transcript asks viewers to buy, "
    "  order, click, act now, or implies urgent conversion.\n"
    "- importance_score: overall clip-worthiness for a natural "
    "  product-introduction short. Prefer speech that clearly "
    "  introduces the product/category, explains benefits, "
    "  demonstrates usage, compares value, includes a natural "
    "  transition, or gives purchase motivation.\n"
    "\n"
    "- primary_catalog_match: 1.0 means this chunk is entirely "
    "  about the primary catalog (the one provided in the user "
    "  message's 'primary_catalog'). 0.0 means it's about a "
    "  different selected catalog (one of 'other_catalogs'). "
    "  0.5 means mixed mentions. When 'primary_catalog' is not "
    "  provided in the user message, return 1.0.\n"
    "\n"
    "Be deterministic. Do not infer facts not present in the "
    "transcript."
)


_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "chunk_score_batch",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["scores"],
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["hook_score", "has_cta", "importance_score", "primary_catalog_match"],
                    "properties": {
                        "hook_score": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "has_cta": {"type": "boolean"},
                        "importance_score": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "primary_catalog_match": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                },
            }
        },
    },
}


class _ChunkScoreItem(BaseModel):
    hook_score: float = Field(ge=0.0, le=1.0)
    has_cta: bool
    importance_score: float = Field(ge=0.0, le=1.0)
    # default 1.0 keeps back-compat — if LLM somehow omits
    # the field (shouldn't happen given strict schema), score defaults
    # to "fully matches primary".
    primary_catalog_match: float = Field(default=1.0, ge=0.0, le=1.0)


class _ChunkScoreBatch(BaseModel):
    scores: list[_ChunkScoreItem]


@dataclass(frozen=True)
class _ChunkInput:
    """Pre-LLM chunk shape. Internal only."""

    start_ms: int
    end_ms: int
    transcript: str


# ---------- public entrypoint ----------


async def score_segment_chunks(
    *,
    segment: MentionSegment,
    openai_client: Any,
    model: str = "gpt-4o-mini",
    timeout_s: float = 15.0,
    chunk_size_ms: int = 20_000,
    # chunk-level LLM catalog match
    primary_catalog_name: str | None = None,
    primary_aliases: list[str] | None = None,
    other_catalog_names: list[str] | None = None,
    catalog_match_threshold: float = 0.0,
) -> list[ScoredChunk]:
    """Slice a segment into chunks, score each via gpt-4o-mini.

    On any LLM defect (timeout, hallucinated count mismatch, JSON
    parse, schema validation, budget exceeded) every chunk in the
    segment falls back to the heuristic baseline. We DO NOT raise —
    a heuristic-scored segment is better than no clip.
    """
    chunk_inputs = _build_chunk_inputs(segment, chunk_size_ms)
    if not chunk_inputs:
        logger.info(
            "stt_chunk_scoring_empty_segment",
            extra={
                "segment_start_ms": segment.start_ms,
                "segment_end_ms": segment.end_ms,
            },
        )
        return []

    scores: list[ChunkScore] = []
    for batch in _batched(chunk_inputs, _MAX_CHUNKS_PER_REQUEST):
        scores.extend(
            await _score_one_batch(
                chunks=batch,
                openai_client=openai_client,
                model=model,
                timeout_s=timeout_s,
                primary_catalog_name=primary_catalog_name,
                primary_aliases=primary_aliases or [],
                other_catalog_names=other_catalog_names or [],
            )
        )

    assert len(scores) == len(chunk_inputs)  # invariant of _score_one_batch
    scored = [
        ScoredChunk(
            start_ms=chunk.start_ms,
            end_ms=chunk.end_ms,
            text=chunk.transcript,
            score=score,
        )
        for chunk, score in zip(chunk_inputs, scores, strict=True)
    ]
    # threshold-based chunk reject. No-op when threshold <= 0.
    if catalog_match_threshold > 0.0:
        before_count = len(scored)
        scored = [
            sc for sc in scored
            if sc.score.primary_catalog_match >= catalog_match_threshold
        ]
        logger.info(
            "stt_chunk_catalog_match_filter",
            extra={
                "threshold": catalog_match_threshold,
                "kept": len(scored),
                "dropped": before_count - len(scored),
            },
        )
    return scored


# ---------- internals ----------


def _build_chunk_inputs(
    segment: MentionSegment, chunk_size_ms: int,
) -> list[_ChunkInput]:
    """Slice a segment into fixed-width chunks, attaching the
    transcript_text from any underlying scenes that overlap each
    chunk. Pure function.
    """
    chunk_size = min(_CHUNK_MAX_MS, max(_CHUNK_MIN_MS, chunk_size_ms))
    chunks: list[_ChunkInput] = []
    cursor = segment.start_ms

    while cursor < segment.end_ms:
        chunk_end = min(segment.end_ms, cursor + chunk_size)
        # Concatenate transcript text from scenes that overlap this
        # chunk window. Scene granularity is coarser than chunk
        # granularity; one scene's transcript may span multiple
        # chunks, in which case the same text appears in each. The
        # LLM gets the right textual context regardless.
        overlapping_text_parts: list[str] = []
        for scene in segment.scenes:
            if scene.start_ms < chunk_end and scene.end_ms > cursor:
                # Prefer transcript_raw; fall back to scene_caption
                # so caption-only videos (gd_bb9c22c2c00d180c-style)
                # still get scored.
                text = scene.transcript_text or scene.caption_text
                if text:
                    overlapping_text_parts.append(text)
        transcript = " ".join(overlapping_text_parts).strip()
        chunks.append(
            _ChunkInput(
                start_ms=cursor,
                end_ms=chunk_end,
                transcript=transcript,
            )
        )
        cursor = chunk_end

    return chunks


async def _score_one_batch(
    *,
    chunks: list[_ChunkInput],
    openai_client: Any,
    model: str,
    timeout_s: float,
    primary_catalog_name: str | None = None,
    primary_aliases: list[str] | None = None,
    other_catalog_names: list[str] | None = None,
) -> list[ChunkScore]:
    """One LLM call. Returns one ChunkScore per input chunk. On any
    defect, returns heuristic scores so the caller can keep going.
    """
    if not chunks:
        return []

    payload_chunks = [
        {
            "start_ms": c.start_ms,
            "end_ms": c.end_ms,
            "transcript": c.transcript,
        }
        for c in chunks
    ]
    payload: dict[str, Any] = {"chunks": payload_chunks}
    if primary_catalog_name:
        payload["primary_catalog"] = {
            "name": primary_catalog_name,
            "aliases": list(primary_aliases or []),
        }
    if other_catalog_names:
        payload["other_catalogs"] = list(other_catalog_names)

    try:
        response = await openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": _RESPONSE_JSON_SCHEMA,
            },
            temperature=0.0,
            seed=42,
            max_tokens=700,
            timeout=timeout_s,
        )
    except Exception as e:  # noqa: BLE001 — fall back, never raise
        logger.warning(
            "stt_chunk_scoring_llm_failed_fallback_heuristic",
            extra={
                "chunk_count": len(chunks),
                "error_type": type(e).__name__,
                "error": str(e)[:300],
            },
        )
        return _heuristic_batch(len(chunks))

    raw = response.choices[0].message.content or ""
    parsed = _parse_or_fallback(raw, expected_count=len(chunks))
    return parsed


def _parse_or_fallback(
    raw_text: str, *, expected_count: int,
) -> list[ChunkScore]:
    """Parse LLM JSON → ChunkScore[]. Any defect → heuristic batch."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning(
            "stt_chunk_scoring_json_parse_failed_fallback",
            extra={"raw_head": raw_text[:200]},
        )
        return _heuristic_batch(expected_count)

    try:
        batch = _ChunkScoreBatch.model_validate(data)
    except ValidationError as e:
        logger.warning(
            "stt_chunk_scoring_schema_validation_failed_fallback",
            extra={"error": str(e)[:200]},
        )
        return _heuristic_batch(expected_count)

    if len(batch.scores) != expected_count:
        logger.warning(
            "stt_chunk_scoring_count_mismatch_fallback",
            extra={
                "expected": expected_count,
                "got": len(batch.scores),
            },
        )
        return _heuristic_batch(expected_count)

    return [
        ChunkScore(
            hook_score=item.hook_score,
            has_cta=item.has_cta,
            importance_score=item.importance_score,
            primary_catalog_match=item.primary_catalog_match,
        )
        for item in batch.scores
    ]


def _heuristic_batch(count: int) -> list[ChunkScore]:
    """Deterministic baseline. ``primary_catalog_match=1.0`` so 
    the threshold filter doesn't reject heuristic chunks — when
    the LLM is down we don't have a catalog signal anyway, and
    keeping chunks lets the pipeline produce output.
    """
    return [
        ChunkScore(
            hook_score=_HEURISTIC_HOOK,
            has_cta=_HEURISTIC_HAS_CTA,
            importance_score=_HEURISTIC_IMPORTANCE,
            primary_catalog_match=1.0,
        )
        for _ in range(count)
    ]


def _batched(
    items: list[_ChunkInput], size: int,
) -> list[list[_ChunkInput]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
