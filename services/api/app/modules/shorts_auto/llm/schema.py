"""JSON schema for the LLM picker response + Pydantic parse.

Two halves of the same contract: the strict JSON schema is passed to
OpenAI's ``response_format={"type": "json_schema"}`` so the model is
forced to emit valid output; the matching Pydantic model parses what
comes back. Keeping them in one file makes drift immediately obvious.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class LLMPick(BaseModel):
    scene_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=240)


class LLMResponse(BaseModel):
    picks: list[LLMPick] = Field(min_length=1, max_length=20)
    overall_rationale: str = Field(default="", max_length=480)

    @field_validator("picks")
    @classmethod
    def _pick_ids_unique(cls, v: list[LLMPick]) -> list[LLMPick]:
        seen: set[str] = set()
        for p in v:
            if p.scene_id in seen:
                raise ValueError(f"duplicate scene_id in picks: {p.scene_id!r}")
            seen.add(p.scene_id)
        return v


# The JSON Schema passed to response_format. Must be self-describing,
# strict, and keep key names identical to LLMResponse. OpenAI's json_schema
# mode requires ``additionalProperties: false`` at every level.
RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "shorts_auto_llm_picks",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["picks", "overall_rationale"],
        "properties": {
            "picks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["scene_id", "score", "reason"],
                    "properties": {
                        "scene_id": {"type": "string", "minLength": 1},
                        "score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "reason": {"type": "string", "maxLength": 240},
                    },
                },
            },
            "overall_rationale": {"type": "string", "maxLength": 480},
        },
    },
}
