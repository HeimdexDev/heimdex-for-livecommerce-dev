"""Tier C JSON schema + Pydantic validators.

Plan: ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md``.

Two layers of validation, both run on the LLM response:

1. ``_RESPONSE_JSON_SCHEMA`` — handed to OpenAI's structured-output
   ``response_format={"type": "json_schema", ...}``. The server
   refuses to return malformed JSON; this is the FIRST defense.

2. ``_LlmPlanResponse`` (Pydantic) — defense-in-depth on the Python
   side. Catches:
   - Slot count violations (must be exactly 1× HOOK, 1× INTRO, 1× CTA, 1-2× DETAIL).
   - Duplicate ``chunk_index`` across fragments.
   - Out-of-bounds ``chunk_index`` is checked SEPARATELY in
     ``llm_picker._validate_semantic_constraints`` because that
     check requires the original ``all_chunks`` list as context;
     keep it out of the Pydantic model so the model stays pure.

The picker translates ``_LlmPlanResponse`` ↔ ``StoryboardPlan`` after
both layers pass. A failure at either layer triggers fallback to
``HeuristicStoryboardPicker``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ====================================================================
# OpenAI structured-output schema. Sent verbatim as ``response_format``.
# ``strict=True`` enables the server-side enforcement layer (no extra
# fields, exact type matching, enum membership).
# ====================================================================
_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "storyboard_plan",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["fragments", "global_rationale"],
        "properties": {
            "fragments": {
                "type": "array",
                "minItems": 4,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["role", "chunk_index", "rationale"],
                    "properties": {
                        "role": {
                            "type": "string",
                            "enum": ["hook", "intro", "detail", "cta"],
                        },
                        "chunk_index": {
                            "type": "integer",
                            "minimum": 0,
                        },
                        "rationale": {
                            "type": "string",
                            "maxLength": 200,
                        },
                    },
                },
            },
            "global_rationale": {
                "type": "string",
                "maxLength": 500,
            },
        },
    },
}


class _LlmFragmentPick(BaseModel):
    """One fragment as returned by the LLM.

    ``role`` is intentionally a Literal of lowercase strings so it
    aligns with ``SlotRole`` enum values without requiring an
    explicit enum import (avoids Pydantic-Enum shenanigans). The
    picker maps these strings → ``SlotRole`` after validation.
    """

    role: Literal["hook", "intro", "detail", "cta"]
    chunk_index: int = Field(ge=0)
    rationale: str = Field(default="", max_length=200)

    @field_validator("rationale", mode="before")
    @classmethod
    def _coerce_rationale_to_str(cls, v: Any) -> str:
        # Defensive: OpenAI strict mode enforces ``string`` but in case
        # a future SDK quirk ever lets ``None`` through, coerce to "".
        # ``max_length`` ensures we don't burn log space on long text.
        if v is None:
            return ""
        return str(v)


class _LlmPlanResponse(BaseModel):
    """Top-level LLM response shape.

    The semantic constraints layered on top here are RESPONSE-INTRINSIC
    (slot counts, no chunk reuse). Constraints that need the original
    chunk list as context (chunk_index in bounds, HOOK in first third,
    CTA in last third) live in
    ``llm_picker._validate_semantic_constraints`` — keeping them out of
    Pydantic preserves this model as a pure response-shape contract.
    """

    fragments: list[_LlmFragmentPick]
    global_rationale: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check_slot_counts(self) -> "_LlmPlanResponse":
        roles = [f.role for f in self.fragments]
        n_hook = roles.count("hook")
        n_intro = roles.count("intro")
        n_cta = roles.count("cta")
        n_detail = roles.count("detail")
        if n_hook != 1:
            raise ValueError(
                f"HOOK must appear exactly once (got {n_hook})"
            )
        if n_intro != 1:
            raise ValueError(
                f"INTRO must appear exactly once (got {n_intro})"
            )
        if n_cta != 1:
            raise ValueError(
                f"CTA must appear exactly once (got {n_cta})"
            )
        if not 1 <= n_detail <= 2:
            raise ValueError(
                f"DETAIL must appear 1 or 2 times (got {n_detail})"
            )
        # No chunk_index reused across fragments.
        indices = [f.chunk_index for f in self.fragments]
        if len(set(indices)) != len(indices):
            raise ValueError(
                f"chunk_index must be unique across fragments (got {indices})"
            )
        return self


__all__ = [
    "_RESPONSE_JSON_SCHEMA",
    "_LlmFragmentPick",
    "_LlmPlanResponse",
]
