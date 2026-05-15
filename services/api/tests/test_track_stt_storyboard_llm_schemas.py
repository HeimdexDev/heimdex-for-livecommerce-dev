"""Tests for the Tier C JSON schema + Pydantic validators.

Plan: ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md`` PR 4.

Pure validation tests — no LLM calls. Bounds checks for the
RESPONSE shape; the chunk_index-out-of-bounds + temporal-ordering
constraints live in `llm_picker._validate_semantic_constraints`
(separate test module).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.shorts_auto_product.track_stt.storyboard.llm_schemas import (
    _RESPONSE_JSON_SCHEMA,
    _LlmFragmentPick,
    _LlmPlanResponse,
)


def _well_formed_response() -> dict:
    """A minimal valid response — 1× HOOK, 1× INTRO, 1× DETAIL, 1× CTA."""
    return {
        "fragments": [
            {"role": "hook", "chunk_index": 0, "rationale": "opens with energy"},
            {"role": "intro", "chunk_index": 1, "rationale": "names product"},
            {"role": "detail", "chunk_index": 2, "rationale": "demo"},
            {"role": "cta", "chunk_index": 3, "rationale": "buy now"},
        ],
        "global_rationale": "narrative arc",
    }


class TestSchemaShape:
    def test_strict_mode_enabled(self):
        assert _RESPONSE_JSON_SCHEMA["strict"] is True

    def test_required_top_level_fields(self):
        required = set(_RESPONSE_JSON_SCHEMA["schema"]["required"])
        assert required == {"fragments", "global_rationale"}

    def test_role_enum(self):
        role_schema = (
            _RESPONSE_JSON_SCHEMA["schema"]["properties"]["fragments"]
            ["items"]["properties"]["role"]
        )
        assert set(role_schema["enum"]) == {"hook", "intro", "detail", "cta"}

    def test_fragment_count_bounds(self):
        frag_schema = _RESPONSE_JSON_SCHEMA["schema"]["properties"]["fragments"]
        assert frag_schema["minItems"] == 4
        assert frag_schema["maxItems"] == 5

    def test_chunk_index_minimum(self):
        ci_schema = (
            _RESPONSE_JSON_SCHEMA["schema"]["properties"]["fragments"]
            ["items"]["properties"]["chunk_index"]
        )
        assert ci_schema["type"] == "integer"
        assert ci_schema["minimum"] == 0


class TestPydanticHappyPath:
    def test_well_formed_validates(self):
        resp = _LlmPlanResponse.model_validate(_well_formed_response())
        assert len(resp.fragments) == 4
        assert resp.fragments[0].role == "hook"
        assert resp.global_rationale == "narrative arc"

    def test_two_detail_fragments_ok(self):
        body = _well_formed_response()
        body["fragments"].append(
            {"role": "detail", "chunk_index": 4, "rationale": "second detail"}
        )
        resp = _LlmPlanResponse.model_validate(body)
        assert len([f for f in resp.fragments if f.role == "detail"]) == 2


class TestSlotCountValidation:
    def test_zero_hooks_rejected(self):
        body = _well_formed_response()
        body["fragments"][0]["role"] = "intro"  # now 0× hook, 2× intro
        with pytest.raises(ValidationError) as exc:
            _LlmPlanResponse.model_validate(body)
        assert "HOOK must appear exactly once" in str(exc.value)

    def test_two_hooks_rejected(self):
        body = _well_formed_response()
        body["fragments"][1]["role"] = "hook"
        with pytest.raises(ValidationError) as exc:
            _LlmPlanResponse.model_validate(body)
        assert "HOOK must appear exactly once" in str(exc.value)

    def test_three_details_rejected(self):
        body = _well_formed_response()
        body["fragments"].extend([
            {"role": "detail", "chunk_index": 4, "rationale": "d2"},
            {"role": "detail", "chunk_index": 5, "rationale": "d3"},
        ])
        # 4 frags + 2 = 6 frags > maxItems=5 (Pydantic) but also
        # n_detail=3 violation. Either fires; we check the latter
        # message because it's more informative.
        with pytest.raises(ValidationError) as exc:
            _LlmPlanResponse.model_validate(body)
        msg = str(exc.value)
        assert "DETAIL must appear 1 or 2 times" in msg or "too_long" in msg

    def test_zero_details_rejected(self):
        body = _well_formed_response()
        body["fragments"][2]["role"] = "intro"  # now 0× detail, 2× intro
        with pytest.raises(ValidationError):
            _LlmPlanResponse.model_validate(body)


class TestChunkIndexUniqueness:
    def test_duplicate_chunk_index_rejected(self):
        body = _well_formed_response()
        body["fragments"][1]["chunk_index"] = 0  # collides with hook
        with pytest.raises(ValidationError) as exc:
            _LlmPlanResponse.model_validate(body)
        assert "chunk_index must be unique" in str(exc.value)


class TestRationaleHandling:
    def test_max_length_enforced(self):
        body = _well_formed_response()
        body["fragments"][0]["rationale"] = "x" * 250
        with pytest.raises(ValidationError):
            _LlmPlanResponse.model_validate(body)

    def test_none_coerced_to_empty(self):
        # Defensive: server-side strict should never let None through,
        # but the validator coerces just in case.
        f = _LlmFragmentPick.model_validate(
            {"role": "hook", "chunk_index": 0, "rationale": None}
        )
        assert f.rationale == ""


class TestRoleStringNormalization:
    def test_uppercase_role_rejected(self):
        # Literal["hook", ...] — only lowercase accepted.
        with pytest.raises(ValidationError):
            _LlmFragmentPick.model_validate(
                {"role": "HOOK", "chunk_index": 0, "rationale": "x"}
            )

    def test_unknown_role_rejected(self):
        with pytest.raises(ValidationError):
            _LlmFragmentPick.model_validate(
                {"role": "outro", "chunk_index": 0, "rationale": "x"}
            )
