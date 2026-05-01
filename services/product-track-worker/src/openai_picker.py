"""gpt-4o-mini-backed :class:`SubsetPicker` impl.

Per plan §6.2 step 7: the LLM picks the final subset of appearance
windows that fits the duration preset, optimizing the composite
score with a chronological-ordering preference and a hard duration
cap.

Inputs (per window): start_ms, end_ms, duration_ms, composite_score,
score_components (already computed by
:func:`heimdex_media_pipelines.product_track.score_windows`). Pre-
computing the score and feeding it to the LLM (rather than asking
the LLM to score) cuts the prompt token cost ~3x and removes the
"LLM ignores the rubric" failure mode.

Failure modes (each falls back to :class:`GreedyPicker` so the job
never hangs on a flaky LLM call):
* HTTP timeout / 5xx → log + fall back
* JSON-mode parse failure → log + fall back
* Selected indices out of range / yield empty subset → log +
  fall back
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from heimdex_media_pipelines.product_track.config import TrackingConfig
from heimdex_media_pipelines.product_track.subset_selector import (
    GreedyPicker,
    ScoredWindow,
)

if TYPE_CHECKING:  # pragma: no cover
    from openai import OpenAI

logger = logging.getLogger(__name__)


_RESPONSE_SCHEMA = {
    "name": "subset_pick_response",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["selected_indices"],
        "properties": {
            "selected_indices": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0},
                "minItems": 1,
            },
        },
    },
}


_SYSTEM_PROMPT = """You are an editor selecting clips for a 30/60/90-second product showcase reel.

Inputs (already pre-scored by an upstream system):
* duration_target_sec — the total length of the reel
* candidates — array of {index, scene_id, start_ms, end_ms, duration_ms, composite_score, score_components}

Selection rubric:
1. Total duration MUST NOT exceed duration_target_sec * 1.05.
2. Prefer windows with higher composite_score.
3. Prefer chronological coverage (windows from different timeline positions over clustering).
4. 3-5 windows is the typical target.
5. Return the indices of selected candidates.
"""


class OpenAIPicker:
    """Concrete :class:`SubsetPicker` impl. ``client`` is an
    ``openai.OpenAI`` instance (lazy-imported so this module is
    test-friendly without the ``openai`` package installed)."""

    def __init__(
        self,
        *,
        client: "OpenAI",
        model: str = "gpt-4o-mini",
        timeout_sec: float = 30.0,
    ) -> None:
        self._client = client
        self._model = model
        self._timeout_sec = timeout_sec
        self._fallback = GreedyPicker()

    def pick(
        self,
        candidates: list[ScoredWindow],
        *,
        duration_preset_sec: int,
        config: TrackingConfig,
    ) -> list[ScoredWindow]:
        if not candidates:
            return []

        try:
            indices = self._call_llm(candidates, duration_preset_sec)
        except Exception:
            logger.exception("openai_picker_call_failed_falling_back_to_greedy")
            return self._fallback.pick(
                candidates,
                duration_preset_sec=duration_preset_sec,
                config=config,
            )

        if not indices:
            logger.warning("openai_picker_returned_empty_falling_back_to_greedy")
            return self._fallback.pick(
                candidates,
                duration_preset_sec=duration_preset_sec,
                config=config,
            )

        # Validate indices are in range; fall back if any out-of-range
        # so a hallucinated index doesn't cause an IndexError.
        max_idx = len(candidates) - 1
        if any(i < 0 or i > max_idx for i in indices):
            logger.warning(
                "openai_picker_out_of_range_indices_falling_back_to_greedy",
                extra={"max_idx": max_idx, "indices": indices},
            )
            return self._fallback.pick(
                candidates,
                duration_preset_sec=duration_preset_sec,
                config=config,
            )

        # Deduplicate (LLM occasionally repeats) + preserve order.
        seen: set[int] = set()
        unique = []
        for i in indices:
            if i not in seen:
                seen.add(i)
                unique.append(i)

        return [candidates[i] for i in unique]

    def _call_llm(
        self,
        candidates: list[ScoredWindow],
        duration_preset_sec: int,
    ) -> list[int]:
        user_payload = {
            "duration_target_sec": duration_preset_sec,
            "candidates": [
                {
                    "index": i,
                    "scene_id": c.window.scene_id,
                    "start_ms": c.window.window_start_ms,
                    "end_ms": c.window.window_end_ms,
                    "duration_ms": c.window.duration_ms,
                    "composite_score": round(c.composite_score, 4),
                    "score_components": {
                        k: round(v, 4) for k, v in c.score_components.items()
                    },
                }
                for i, c in enumerate(candidates)
            ],
        }

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": _RESPONSE_SCHEMA,
            },
            timeout=self._timeout_sec,
        )

        content = resp.choices[0].message.content or "{}"
        parsed = json.loads(content)
        return [int(i) for i in parsed.get("selected_indices", [])]
