"""Unit tests for OpenAILLMScorer with all IO mocked.

Covers the fallback contract the plan promised: every LLM defect
(timeout, terminal, JSON parse, schema, hallucinated scene_id,
over-duration, budget) must raise ScorerFallbackSignal or
ScorerBudgetExceededError — never 5xx up to the service.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.modules.shorts_auto.llm.budget import (
    BudgetExceededError,
    InMemoryBudgetTracker,
)
from app.modules.shorts_auto.llm.client import (
    LLMCallResult,
    LLMRetryableError,
    LLMTerminalError,
    TokenUsage,
)
from app.modules.shorts_auto.scorers import (
    OpenAILLMScorer,
    ScorerBudgetExceededError,
    ScorerFallbackSignal,
    ScoringContext,
)
from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.scorer import ScoringMode


def _scene(short: str, start_ms: int = 0, end_ms: int = 10_000, *, video_id: str = "vid") -> SceneDocument:
    """Build a valid SceneDocument whose scene_id follows the required
    ``{video_id}_scene_{index:03d}`` format. ``short`` is a stable label
    used only for test readability; the real scene_id is derived.
    """
    # Derive a deterministic index from ``short`` so tests can compare
    # by label via the returned scene_id prefix.
    index = int("".join(c for c in short if c.isdigit()) or "0")
    return SceneDocument(
        scene_id=f"{video_id}_scene_{index:03d}",
        video_id=video_id,
        index=index,
        start_ms=start_ms,
        end_ms=end_ms,
        keyframe_timestamp_ms=(start_ms + end_ms) // 2,
    )


def _ctx() -> ScoringContext:
    return ScoringContext(
        mode=ScoringMode.BOTH,
        target_duration_sec=60,
        video_id="vid",
    )


def _llm_result(payload: dict | str) -> LLMCallResult:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return LLMCallResult(
        text=text,
        usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        model="gpt-4o-mini",
        cost_usd=0.001,
        latency_ms=500,
    )


def _make_scorer(client_call_mock: AsyncMock, max_scenes: int = 50) -> OpenAILLMScorer:
    # Construct a minimally-valid OpenAILLMScorer without touching the
    # openai SDK. We build the class directly and inject a client-shaped
    # object; the scorer only calls ``client.call`` + reads ``client.model``.
    scorer = OpenAILLMScorer.__new__(OpenAILLMScorer)
    scorer._client = _FakeClient(client_call_mock)  # type: ignore[attr-defined]
    scorer._max_scenes = max_scenes  # type: ignore[attr-defined]
    scorer._prompt_version = "test-v1"  # type: ignore[attr-defined]
    return scorer


class _FakeClient:
    model = "gpt-4o-mini"

    def __init__(self, call_mock: AsyncMock) -> None:
        self.call = call_mock


@pytest.mark.asyncio
async def test_happy_path_returns_picked_scored_scenes():
    scenes = [_scene("1"), _scene("2", 10_000, 20_000), _scene("3", 20_000, 30_000)]
    mock = AsyncMock(
        return_value=_llm_result(
            {
                "picks": [
                    {"scene_id": "vid_scene_001", "score": 0.9, "reason": "ok"},
                    {"scene_id": "vid_scene_003", "score": 0.7, "reason": "ok"},
                ],
                "overall_rationale": "variety",
            }
        )
    )
    scorer = _make_scorer(mock)
    result = await scorer.score(scenes, _ctx())

    # All input scenes should be reflected; picked=eligible, others not.
    by_id = {s.scene.scene_id: s for s in result}
    assert by_id["vid_scene_001"].breakdown.eligible is True
    assert by_id["vid_scene_001"].breakdown.total == pytest.approx(0.9)
    assert by_id["vid_scene_002"].breakdown.eligible is False
    assert by_id["vid_scene_003"].breakdown.eligible is True


@pytest.mark.asyncio
async def test_hallucinated_scene_id_triggers_fallback():
    scenes = [_scene("1"), _scene("2", 10_000, 20_000)]
    mock = AsyncMock(
        return_value=_llm_result(
            {
                "picks": [
                    {"scene_id": "vid_scene_001", "score": 0.9, "reason": "real"},
                    {"scene_id": "not-in-corpus", "score": 0.8, "reason": "fake"},
                ],
                "overall_rationale": "",
            }
        )
    )
    scorer = _make_scorer(mock)
    with pytest.raises(ScorerFallbackSignal, match="hallucinated_scene_ids"):
        await scorer.score(scenes, _ctx())


@pytest.mark.asyncio
async def test_over_duration_picks_trigger_fallback():
    # Two 60s scenes picked → 120s total > 90s cap.
    scenes = [
        _scene("1", 0, 60_000),
        _scene("2", 60_000, 120_000),
    ]
    mock = AsyncMock(
        return_value=_llm_result(
            {
                "picks": [
                    {"scene_id": "vid_scene_001", "score": 0.9, "reason": ""},
                    {"scene_id": "vid_scene_002", "score": 0.9, "reason": ""},
                ],
                "overall_rationale": "",
            }
        )
    )
    scorer = _make_scorer(mock)
    with pytest.raises(ScorerFallbackSignal, match="over_duration"):
        await scorer.score(scenes, _ctx())


@pytest.mark.asyncio
async def test_invalid_json_triggers_fallback():
    mock = AsyncMock(return_value=_llm_result("not json at all"))
    scorer = _make_scorer(mock)
    with pytest.raises(ScorerFallbackSignal, match="json_parse_failed"):
        await scorer.score([_scene("1")], _ctx())


@pytest.mark.asyncio
async def test_schema_validation_failure_triggers_fallback():
    # Missing required "picks" field.
    mock = AsyncMock(return_value=_llm_result({"overall_rationale": "missing picks"}))
    scorer = _make_scorer(mock)
    with pytest.raises(ScorerFallbackSignal, match="schema_validation_failed"):
        await scorer.score([_scene("1")], _ctx())


@pytest.mark.asyncio
async def test_terminal_llm_error_triggers_fallback():
    mock = AsyncMock(side_effect=LLMTerminalError("401 bad auth"))
    scorer = _make_scorer(mock)
    with pytest.raises(ScorerFallbackSignal, match="terminal"):
        await scorer.score([_scene("1")], _ctx())


@pytest.mark.asyncio
async def test_retryable_exhausted_triggers_fallback():
    mock = AsyncMock(side_effect=LLMRetryableError("500 after 3 retries"))
    scorer = _make_scorer(mock)
    with pytest.raises(ScorerFallbackSignal, match="retryable_exhausted"):
        await scorer.score([_scene("1")], _ctx())


@pytest.mark.asyncio
async def test_budget_exceeded_raises_budget_error_not_fallback_signal():
    mock = AsyncMock(side_effect=BudgetExceededError("daily cap"))
    scorer = _make_scorer(mock)
    with pytest.raises(ScorerBudgetExceededError):
        await scorer.score([_scene("1")], _ctx())


@pytest.mark.asyncio
async def test_empty_scene_list_short_circuits():
    mock = AsyncMock()
    scorer = _make_scorer(mock)
    assert await scorer.score([], _ctx()) == []
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_max_scenes_caps_corpus():
    scenes = [_scene(str(i), i * 10_000, (i + 1) * 10_000) for i in range(60)]
    mock = AsyncMock(
        return_value=_llm_result(
            {
                "picks": [{"scene_id": "vid_scene_000", "score": 0.8, "reason": ""}],
                "overall_rationale": "",
            }
        )
    )
    scorer = _make_scorer(mock, max_scenes=10)
    result = await scorer.score(scenes, _ctx())
    # Result only reflects the 10-scene capped corpus.
    assert len(result) == 10


class TestBudgetTracker:
    def test_reserve_then_record_rolls_correctly(self):
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.5)
        t.record(0.4)
        assert t.spent_today_usd() == pytest.approx(0.4)

    def test_reserve_exceeding_budget_raises(self):
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.8)
        with pytest.raises(BudgetExceededError):
            t.check_and_reserve(0.5)
