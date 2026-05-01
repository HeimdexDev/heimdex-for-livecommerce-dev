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
from decimal import Decimal
from typing import TYPE_CHECKING

from heimdex_media_pipelines.product_track.config import TrackingConfig
from heimdex_media_pipelines.product_track.subset_selector import (
    GreedyPicker,
    ScoredWindow,
)

if TYPE_CHECKING:  # pragma: no cover
    from openai import OpenAI

logger = logging.getLogger(__name__)


# gpt-4o-mini pricing per OpenAI (USD per 1M tokens). When the
# configured model differs from this default, ``total_cost_usd``
# undercounts — cost reporting is best-effort scaffold accuracy and
# Phase 3c-B can swap to the api side computing cost from token
# counts (which are reported precisely).
_GPT_4O_MINI_INPUT_USD_PER_1M = Decimal("0.150")
_GPT_4O_MINI_OUTPUT_USD_PER_1M = Decimal("0.600")


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
        # Accumulated USD spend across all ``pick()`` calls on this
        # instance. The worker reads this AFTER ``select_subset()``
        # to roll the LLM cost into the job's heartbeat / complete
        # ``cost_delta_usd`` so the api's daily-budget gate doesn't
        # undercount tracking jobs that used the LLM picker.
        self.total_cost_usd: Decimal = Decimal("0")

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

        # Honor the duration budget at the picker boundary. The
        # lib's ``select_subset`` will trim oversize picks by dropping
        # low-score windows — but if GPT picks one long window for a
        # short preset, that trim can leave ``selected=[]`` and the
        # whole job fails. Falling back to the greedy picker (which
        # honors the budget structurally) is safer than letting an
        # oversize pick reach the trimmer.
        budget_ms = int(
            duration_preset_sec * 1000
            * config.subset_duration_overshoot_factor
        )
        total_ms = sum(candidates[i].window.duration_ms for i in unique)
        if total_ms > budget_ms:
            logger.warning(
                "openai_picker_exceeds_duration_budget_falling_back_to_greedy",
                extra={
                    "selected_total_ms": total_ms,
                    "budget_ms": budget_ms,
                    "selected_count": len(unique),
                    "duration_preset_sec": duration_preset_sec,
                },
            )
            return self._fallback.pick(
                candidates,
                duration_preset_sec=duration_preset_sec,
                config=config,
            )

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

        # Accumulate cost from the response usage block. The
        # heartbeat / complete callbacks attribute LLM spend to the
        # tracking job's daily budget bucket; pre-fix every track
        # job using the LLM picker reported $0 to the api ledger.
        usage = getattr(resp, "usage", None)
        if usage is not None:
            input_tokens = Decimal(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = Decimal(getattr(usage, "completion_tokens", 0) or 0)
            call_cost = (
                input_tokens * _GPT_4O_MINI_INPUT_USD_PER_1M / Decimal(1_000_000)
                + output_tokens * _GPT_4O_MINI_OUTPUT_USD_PER_1M / Decimal(1_000_000)
            )
            self.total_cost_usd += call_cost
            logger.debug(
                "openai_picker_call_cost",
                extra={
                    "input_tokens": int(input_tokens),
                    "output_tokens": int(output_tokens),
                    "call_cost_usd": str(call_cost),
                    "total_cost_usd": str(self.total_cost_usd),
                },
            )

        content = resp.choices[0].message.content or "{}"
        parsed = json.loads(content)
        return [int(i) for i in parsed.get("selected_indices", [])]
