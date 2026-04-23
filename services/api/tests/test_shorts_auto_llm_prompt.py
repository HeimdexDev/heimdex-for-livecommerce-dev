"""Prompt + schema tests: stable prefix, version bump discipline, schema roundtrip.

These tests are the canary for "don't silently change the prompt":
any edit to ``shorts_auto/llm/prompt.py``'s system message must come
with a PROMPT_VERSION bump, or these tests fail.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.modules.shorts_auto.llm.prompt import (
    PROMPT_VERSION,
    build_prompt,
    system_message,
)
from app.modules.shorts_auto.llm.schema import LLMResponse, RESPONSE_JSON_SCHEMA
from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.scorer import ScoringMode


def _scene(i: int, *, video_id: str = "vid") -> SceneDocument:
    return SceneDocument(
        scene_id=f"{video_id}_scene_{i:03d}",
        video_id=video_id,
        index=i,
        start_ms=i * 10_000,
        end_ms=(i + 1) * 10_000,
        keyframe_timestamp_ms=i * 10_000 + 5_000,
        scene_caption=f"caption {i}",
        transcript_raw=f"transcript {i}",
        product_tags=["bag"] if i % 2 == 0 else [],
    )


class TestSystemMessage:
    def test_is_nonempty_and_mentions_json(self):
        msg = system_message()
        assert len(msg) > 100
        assert "JSON" in msg

    def test_prompt_version_is_dated(self):
        # Gate: bump the version when the system message changes.
        assert PROMPT_VERSION.startswith("2026-")


class TestBuildPrompt:
    def test_returns_system_then_user(self):
        msgs = build_prompt(
            scenes=[_scene(0)],
            mode=ScoringMode.BOTH,
            target_duration_sec=60,
            video_id="vid",
            video_title="t",
            person_cluster_id=None,
        )
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_system_message_is_stable_across_calls(self):
        a = build_prompt(
            scenes=[_scene(0)],
            mode=ScoringMode.BOTH,
            target_duration_sec=60,
            video_id="vid-a",
            video_title="A",
            person_cluster_id=None,
        )
        b = build_prompt(
            scenes=[_scene(1)],
            mode=ScoringMode.PRODUCT,
            target_duration_sec=30,
            video_id="vid-b",
            video_title="B",
            person_cluster_id=None,
        )
        # Stable prefix → OpenAI automatic prompt caching kicks in.
        assert a[0]["content"] == b[0]["content"]

    def test_user_message_includes_all_scene_ids(self):
        scenes = [_scene(i) for i in range(5)]
        expected_ids = [s.scene_id for s in scenes]
        msgs = build_prompt(
            scenes=scenes,
            mode=ScoringMode.BOTH,
            target_duration_sec=60,
            video_id="vid",
            video_title=None,
            person_cluster_id=None,
        )
        user = msgs[1]["content"]
        for sid in expected_ids:
            assert sid in user

    def test_human_mode_includes_person_cluster_id(self):
        msgs = build_prompt(
            scenes=[_scene(0)],
            mode=ScoringMode.HUMAN,
            target_duration_sec=60,
            video_id="vid",
            video_title=None,
            person_cluster_id="person_abc",
        )
        assert "person_abc" in msgs[1]["content"]


class TestResponseSchema:
    def test_llm_response_roundtrip(self):
        data = {
            "picks": [{"scene_id": "a", "score": 0.5, "reason": "ok"}],
            "overall_rationale": "",
        }
        parsed = LLMResponse.model_validate(data)
        assert parsed.picks[0].scene_id == "a"

    def test_rejects_duplicate_scene_ids(self):
        data = {
            "picks": [
                {"scene_id": "a", "score": 0.5, "reason": ""},
                {"scene_id": "a", "score": 0.6, "reason": ""},
            ],
            "overall_rationale": "",
        }
        with pytest.raises(ValidationError, match="duplicate"):
            LLMResponse.model_validate(data)

    def test_rejects_score_out_of_range(self):
        data = {
            "picks": [{"scene_id": "a", "score": 1.5, "reason": ""}],
            "overall_rationale": "",
        }
        with pytest.raises(ValidationError):
            LLMResponse.model_validate(data)

    def test_json_schema_is_strict(self):
        # OpenAI requires additionalProperties:false at every object level.
        assert RESPONSE_JSON_SCHEMA["strict"] is True
        schema = RESPONSE_JSON_SCHEMA["schema"]
        assert schema["additionalProperties"] is False
        item_schema = schema["properties"]["picks"]["items"]
        assert item_schema["additionalProperties"] is False

    def test_json_schema_is_json_serializable(self):
        # Proxy check for "won't crash when we send it to OpenAI".
        s = json.dumps(RESPONSE_JSON_SCHEMA)
        assert "shorts_auto_llm_picks" in s
