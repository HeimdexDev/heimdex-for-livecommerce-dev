"""LLM scene scorer.

Composes the client + prompt + schema + corpus validation, and maps the
LLM's output back to the same ``ScoredScene`` shape the pure scorer
produces. The concatenator downstream sees no difference.

Any defect in the LLM output (timeout, bad JSON, hallucinated scene_id,
over-duration) raises ``ScorerFallbackSignal`` so the service can
re-run the pure scorer on the same request. The service is the ONE
place that knows about fallback — this module just signals.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.concatenator import ScoredScene
from heimdex_media_contracts.shorts.scorer import ScoreBreakdown

from ..llm.budget import BudgetExceededError
from ..llm.client import (
    LLMRetryableError,
    LLMTerminalError,
    OpenAIClipClient,
)
from ..llm.prompt import PROMPT_VERSION, build_prompt
from ..llm.schema import RESPONSE_JSON_SCHEMA, LLMResponse
from .base import (
    SceneScorer,
    ScorerBudgetExceededError,
    ScorerFallbackSignal,
    ScoringContext,
)

logger = logging.getLogger(__name__)


# Max total selected duration before we treat the LLM as over-picking and
# trigger a fallback. 90s lets the concatenator still find good 60s clips
# with some headroom; any more and the picker is ignoring the target.
_MAX_TOTAL_PICK_DURATION_MS = 90_000


@dataclass
class _ValidatedPicks:
    scored: list[ScoredScene]
    rationale: str


class OpenAILLMScorer(SceneScorer):
    name = "llm"

    def __init__(
        self,
        *,
        client: OpenAIClipClient,
        max_scenes: int,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._client = client
        self._max_scenes = max_scenes
        self._prompt_version = prompt_version

    async def score(
        self,
        scenes: list[SceneDocument],
        context: ScoringContext,
    ) -> list[ScoredScene]:
        if not scenes:
            return []

        # Cap the corpus size so latency + token cost stay bounded. We
        # keep the chronologically-first N — the selector already sorts
        # by start_ms ascending, which biases toward earlier scenes. The
        # scorer doesn't care about ordering, only that the scene_ids
        # round-trip.
        corpus = scenes[: self._max_scenes]
        corpus_by_id: dict[str, SceneDocument] = {s.scene_id: s for s in corpus}

        messages = build_prompt(
            scenes=corpus,
            mode=context.mode,
            target_duration_sec=context.target_duration_sec,
            video_id=context.video_id,
            video_title=context.video_title,
            person_cluster_id=context.person_cluster_id,
        )

        # Deterministic seed derived from inputs so retries of the same
        # request produce identical picks. Python hash() is salted per
        # process; use a stable derivation instead.
        seed = _stable_seed(context.video_id, self._prompt_version)

        try:
            result = await self._client.call(
                messages=messages,
                response_format=RESPONSE_JSON_SCHEMA,
                seed=seed,
            )
        except BudgetExceededError as e:
            raise ScorerBudgetExceededError(str(e)) from e
        except LLMTerminalError as e:
            logger.warning(
                "shorts_auto_llm_terminal_error",
                extra={"video_id": context.video_id, "error": str(e)[:300]},
            )
            raise ScorerFallbackSignal(f"terminal: {e}") from e
        except LLMRetryableError as e:
            logger.warning(
                "shorts_auto_llm_retryable_exhausted",
                extra={"video_id": context.video_id, "error": str(e)[:300]},
            )
            raise ScorerFallbackSignal(f"retryable_exhausted: {e}") from e

        validated = _parse_and_validate(
            result.text, corpus_by_id, video_id=context.video_id
        )

        logger.info(
            "shorts_auto_llm_success",
            extra={
                "video_id": context.video_id,
                "mode": context.mode.value,
                "model": self._client.model,
                "prompt_version": self._prompt_version,
                "corpus_size": len(corpus),
                "picks_count": len(validated.scored),
                "cost_usd": result.cost_usd,
                "latency_ms": result.latency_ms,
                "input_tokens": result.usage.prompt_tokens,
                "cached_tokens": result.usage.cached_prompt_tokens,
                "output_tokens": result.usage.completion_tokens,
                "rationale": validated.rationale[:200],
            },
        )
        return validated.scored


def _stable_seed(video_id: str, prompt_version: str) -> int:
    """Deterministic 32-bit seed from (video_id, prompt_version).

    OpenAI accepts any int; we keep it positive + within int32 for
    consistency. Hash(video_id+prompt_version) over SHA1's first 4
    bytes gives collision-resistant determinism across process restarts.
    """
    import hashlib

    digest = hashlib.sha1(f"{video_id}|{prompt_version}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _parse_and_validate(
    raw_text: str,
    corpus_by_id: dict[str, SceneDocument],
    *,
    video_id: str,
) -> _ValidatedPicks:
    """Parse JSON → LLMResponse, validate all scene_ids exist in corpus,
    enforce total duration cap. Any failure → ScorerFallbackSignal.
    """
    try:
        data: Any = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.warning(
            "shorts_auto_llm_json_parse_failed",
            extra={"video_id": video_id, "error": str(e)[:200], "raw_head": raw_text[:200]},
        )
        raise ScorerFallbackSignal("json_parse_failed") from e

    try:
        parsed = LLMResponse.model_validate(data)
    except Exception as e:
        logger.warning(
            "shorts_auto_llm_schema_validation_failed",
            extra={"video_id": video_id, "error": str(e)[:200]},
        )
        raise ScorerFallbackSignal("schema_validation_failed") from e

    # Corpus validation: every picked scene_id must exist in the input.
    hallucinated = [p.scene_id for p in parsed.picks if p.scene_id not in corpus_by_id]
    if hallucinated:
        logger.warning(
            "shorts_auto_llm_hallucinated_scene_ids",
            extra={
                "video_id": video_id,
                "hallucinated_ids": hallucinated[:10],
                "hallucinated_count": len(hallucinated),
            },
        )
        raise ScorerFallbackSignal(f"hallucinated_scene_ids: {len(hallucinated)}")

    # Duration guard: reject over-picks (> 90s total).
    total_ms = sum(
        corpus_by_id[p.scene_id].end_ms - corpus_by_id[p.scene_id].start_ms
        for p in parsed.picks
    )
    if total_ms > _MAX_TOTAL_PICK_DURATION_MS:
        logger.warning(
            "shorts_auto_llm_over_duration",
            extra={
                "video_id": video_id,
                "total_ms": total_ms,
                "cap_ms": _MAX_TOTAL_PICK_DURATION_MS,
                "pick_count": len(parsed.picks),
            },
        )
        raise ScorerFallbackSignal(f"over_duration: {total_ms}ms")

    # Map picks → ScoredScene. LLM decides which scenes are "eligible";
    # scenes it picked are eligible by fiat. Scenes it didn't pick are
    # included with eligible=False so the concatenator can still consider
    # them if it needs headroom — but the scorer bias is strong.
    scored: list[ScoredScene] = []
    picked_set = {p.scene_id for p in parsed.picks}
    pick_by_id = {p.scene_id: p for p in parsed.picks}
    for scene_id, scene in corpus_by_id.items():
        if scene_id in picked_set:
            pick = pick_by_id[scene_id]
            scored.append(
                ScoredScene(
                    scene=scene,
                    breakdown=ScoreBreakdown(
                        eligible=True,
                        total=float(pick.score),
                        reasons=[pick.reason] if pick.reason else [],
                    ),
                )
            )
        else:
            scored.append(
                ScoredScene(
                    scene=scene,
                    breakdown=ScoreBreakdown(
                        eligible=False,
                        total=0.0,
                        reasons=[],
                    ),
                )
            )

    return _ValidatedPicks(scored=scored, rationale=parsed.overall_rationale)
