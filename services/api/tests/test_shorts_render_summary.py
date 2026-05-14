"""Smoke tests for shorts_render summary endpoint.

Pure-function tests for prompt builder. Service-level tests are
deferred to integration since they require OS + OpenAI mocking
infra that conftest already provides for other modules.
"""

from __future__ import annotations

import pytest

from app.modules.shorts_render.summary_prompt import (
    PROMPT_VERSION,
    _SYSTEM_PROMPT,
    _SceneSignals,
    build_user_prompt,
)


class TestPromptVersion:
    def test_v1(self):
        assert PROMPT_VERSION == "v1"

    def test_system_prompt_mentions_evergreen(self):
        low = _SYSTEM_PROMPT.lower()
        assert "evergreen" in low
        assert "korean" in low
        # block-list keywords
        assert "오늘만" in _SYSTEM_PROMPT


class TestUserPromptBuilder:
    def test_includes_all_signals(self):
        scenes = [
            _SceneSignals(
                start_ms=0, end_ms=8000,
                transcript="이거 한번 보세요",
                scene_caption="여성 호스트가 마스크팩을 들고 있음",
                ocr_text="신상 마스크팩",
                speaker_transcript="이거 한번 보세요",
            ),
        ]
        out = build_user_prompt(
            scenes=scenes,
            target_duration_ms=8000,
            max_sentences=2,
        )
        assert "Clip length: 8s" in out
        assert "이거 한번 보세요" in out
        assert "여성 호스트" in out
        assert "신상 마스크팩" in out

    def test_chronological_order(self):
        scenes = [
            _SceneSignals(0, 5000, "first", "", "", ""),
            _SceneSignals(5000, 10000, "second", "", "", ""),
        ]
        out = build_user_prompt(
            scenes=scenes, target_duration_ms=10000, max_sentences=2,
        )
        first_idx = out.find("first")
        second_idx = out.find("second")
        assert 0 < first_idx < second_idx