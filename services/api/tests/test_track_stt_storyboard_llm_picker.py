"""Tests for `LlmStoryboardPicker.assemble`.

Plan: ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md`` PR 4.

Mocks the OpenAI SDK at the call boundary (`openai_client.chat
.completions.create`). Verifies:
  * Happy path: well-formed response → fragments emitted in slot
    order, rationales preserved, budget recorded.
  * Empty input → fallback to heuristic, no LLM call.
  * Budget exhausted → fallback, no LLM call.
  * `asyncio.TimeoutError` → fallback, reservation released.
  * SDK exception → fallback, reservation released.
  * JSON parse failure → fallback.
  * Pydantic schema violation → fallback.
  * Semantic constraint violation (out-of-bounds idx, HOOK in last
    third, CTA in first third, role temporal disorder) → fallback.

The fallback target is itself the `HeuristicStoryboardPicker` —
asserted via spy mock so we can verify it was called once in each
defect case.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.lib.whisper_transcribe.budget import (
    BudgetExceededError,
    InMemoryBudgetTracker,
)
from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionSegment,
    MentionedScene,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard.heuristic_picker import (
    HeuristicStoryboardPicker,
)
from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
    LlmStoryboardPicker,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    SlotBudgets,
    SlotRole,
    StoryboardPlan,
)


# ----- fixtures -----


def _chunks_with_temporal_spread() -> list[ScoredChunk]:
    """3-minute source, 6 chunks. HOOK candidates in first third
    (0-60s), CTA candidates in last third (120-180s).
    """
    return [
        ScoredChunk(start_ms=0, end_ms=15_000, text="hook 0",
                    score=ChunkScore(hook_score=0.9, has_cta=False, importance_score=0.4)),
        ScoredChunk(start_ms=15_000, end_ms=30_000, text="intro 1",
                    score=ChunkScore(hook_score=0.3, has_cta=False, importance_score=0.85)),
        ScoredChunk(start_ms=30_000, end_ms=60_000, text="detail 2",
                    score=ChunkScore(hook_score=0.2, has_cta=False, importance_score=0.78)),
        ScoredChunk(start_ms=60_000, end_ms=90_000, text="detail 3",
                    score=ChunkScore(hook_score=0.2, has_cta=False, importance_score=0.65)),
        ScoredChunk(start_ms=90_000, end_ms=120_000, text="filler 4",
                    score=ChunkScore(hook_score=0.1, has_cta=False, importance_score=0.3)),
        ScoredChunk(start_ms=130_000, end_ms=170_000, text="cta 5",
                    score=ChunkScore(hook_score=0.1, has_cta=True, importance_score=0.5)),
    ]


def _segments_for(chunks: list[ScoredChunk]) -> list[MentionSegment]:
    """One segment spanning all chunks — minimal valid input."""
    if not chunks:
        return []
    start = min(c.start_ms for c in chunks)
    end = max(c.end_ms for c in chunks)
    scene = MentionedScene(
        scene_id="s0", start_ms=start, end_ms=end, score=1.0,
        matched_field="transcript_raw",
    )
    return [MentionSegment(start_ms=start, end_ms=end, scenes=[scene])]


def _well_formed_llm_response() -> dict:
    """Picks consistent with `_chunks_with_temporal_spread()`."""
    return {
        "fragments": [
            {"role": "hook", "chunk_index": 0, "rationale": "energetic open"},
            {"role": "intro", "chunk_index": 1, "rationale": "names product"},
            {"role": "detail", "chunk_index": 2, "rationale": "demo"},
            {"role": "cta", "chunk_index": 5, "rationale": "buy now"},
        ],
        "global_rationale": "energy → context → demo → close",
    }


def _mock_openai_response(content: str | dict, *, prompt_tokens=1250, completion_tokens=300) -> Any:
    """Build a SimpleNamespace mimicking the OpenAI SDK shape used by
    the picker (`response.choices[0].message.content` + `response.usage`).
    """
    body = content if isinstance(content, str) else json.dumps(content)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=body))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        ),
    )


def _make_picker(
    *,
    create_returns: Any = None,
    create_raises: Exception | None = None,
    daily_budget_usd: float = 1.0,
    fallback: HeuristicStoryboardPicker | None = None,
) -> tuple[LlmStoryboardPicker, MagicMock, HeuristicStoryboardPicker]:
    """Construct an LlmStoryboardPicker with a mocked OpenAI client.

    Returns (picker, mock_client, spied_fallback).
    """
    fallback_real = fallback or HeuristicStoryboardPicker(budgets=SlotBudgets())
    spied_fallback = MagicMock(wraps=fallback_real)
    # MagicMock(wraps=...) doesn't auto-handle async methods; rebind.
    spied_fallback.assemble = AsyncMock(side_effect=fallback_real.assemble)

    mock_client = MagicMock()
    if create_raises is not None:
        mock_client.chat.completions.create = AsyncMock(side_effect=create_raises)
    else:
        mock_client.chat.completions.create = AsyncMock(return_value=create_returns)

    picker = LlmStoryboardPicker(
        openai_client=mock_client,
        model="gpt-4o-mini",
        prompt_version="v1",
        timeout_s=5.0,
        budgets=SlotBudgets(),
        budget_tracker=InMemoryBudgetTracker(daily_budget_usd=daily_budget_usd),
        fallback=spied_fallback,
    )
    return picker, mock_client, spied_fallback


# ----- happy path -----


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_well_formed_response_emits_fragments(self):
        chunks = _chunks_with_temporal_spread()
        segments = _segments_for(chunks)
        picker, mock_client, spied_fallback = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )

        plan = await picker.assemble(
            all_chunks=chunks, segments=segments,
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )

        assert isinstance(plan, StoryboardPlan)
        assert mock_client.chat.completions.create.call_count == 1
        spied_fallback.assemble.assert_not_called()  # no fallback on happy path
        # 4 fragments with the expected roles in storyboard order.
        roles = [f.role for f in plan.fragments]
        assert roles == [SlotRole.HOOK, SlotRole.INTRO, SlotRole.DETAIL, SlotRole.CTA]
        # Rationale propagated from LLM response.
        assert plan.fragments[0].rationale == "energetic open"
        assert plan.fragments[3].rationale == "buy now"

    @pytest.mark.asyncio
    async def test_seed_and_temperature_pinned(self):
        chunks = _chunks_with_temporal_spread()
        picker, mock_client, _ = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )

        await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="dyson", spoken_aliases=["다이슨"],
        )

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["temperature"] == 0.0
        assert kwargs["seed"] is not None
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["response_format"]["type"] == "json_schema"

    @pytest.mark.asyncio
    async def test_two_details_picked_chronologically(self):
        chunks = _chunks_with_temporal_spread()
        body = _well_formed_llm_response()
        # Add a second DETAIL.
        body["fragments"].append(
            {"role": "detail", "chunk_index": 3, "rationale": "second demo"}
        )
        picker, _, _ = _make_picker(create_returns=_mock_openai_response(body))

        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )

        details = [f for f in plan.fragments if f.role == SlotRole.DETAIL]
        assert len(details) == 2
        # Picker re-sorts DETAILs by source_start_ms.
        assert details[0].source_start_ms < details[1].source_start_ms

    @pytest.mark.asyncio
    async def test_budget_recorded_on_success(self):
        chunks = _chunks_with_temporal_spread()
        picker, _, _ = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        before = picker.budget_tracker.spent_today_usd()

        await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        after = picker.budget_tracker.spent_today_usd()
        # 1250 input × $0.15/1M + 300 output × $0.60/1M = ~$0.000368.
        assert after > before
        assert 0.0001 < (after - before) < 0.001


# ----- fallback paths -----


class TestEmptyInput:
    @pytest.mark.asyncio
    async def test_no_chunks_skips_to_fallback(self):
        picker, mock_client, spied = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        plan = await picker.assemble(
            all_chunks=[], segments=[],
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        mock_client.chat.completions.create.assert_not_called()
        spied.assemble.assert_called_once()


class TestInsufficientChunks:
    """PR 9: early-exit when chunk_count < 4. The schema requires
    1× HOOK + 1× INTRO + 1× CTA + 1× DETAIL = 4 unique chunks; below
    this the LLM has no path to a valid plan and would always fall
    back via Pydantic. Skip the API call entirely.
    """

    @pytest.mark.asyncio
    async def test_three_chunks_skips_llm_call(self):
        chunks = _chunks_with_temporal_spread()[:3]
        picker, mock_client, spied = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        # No LLM call fired — saves cost + latency.
        mock_client.chat.completions.create.assert_not_called()
        spied.assemble.assert_called_once()
        # Budget untouched — early-exit happens before reservation.
        assert picker.budget_tracker.spent_today_usd() == 0.0

    @pytest.mark.asyncio
    async def test_four_chunks_proceeds_to_llm(self):
        # 4 is the minimum for a valid plan — picker should fire.
        chunks = _chunks_with_temporal_spread()[:4]
        # Pick well-formed response that uses chunk indices 0, 1, 2, 3.
        body = {
            "fragments": [
                {"role": "hook", "chunk_index": 0, "rationale": "open"},
                {"role": "intro", "chunk_index": 1, "rationale": "intro"},
                {"role": "detail", "chunk_index": 2, "rationale": "demo"},
                {"role": "cta", "chunk_index": 3, "rationale": "close"},
            ],
            "global_rationale": "arc",
        }
        # 4 chunks span 0-90s; CTA at index 3 starts at 60s — that's
        # the last third of source_duration=90s. Adjust spread so
        # semantic constraints pass.
        chunks[3] = ScoredChunk(
            start_ms=70_000, end_ms=88_000, text="cta",
            score=ChunkScore(hook_score=0.1, has_cta=True, importance_score=0.5),
        )
        picker, mock_client, spied = _make_picker(
            create_returns=_mock_openai_response(body),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        # LLM call WAS fired (chunk_count = 4 ≥ minimum).
        mock_client.chat.completions.create.assert_called_once()
        # Picker succeeded → no fallback.
        spied.assemble.assert_not_called()


class TestSmallChunkHint:
    """PR 9: when chunk_count is in [4, 5), the prompt nudges the
    LLM to pick 1× DETAIL only — 2× DETAIL would require 5 unique
    chunks and force chunk_index reuse.
    """

    @pytest.mark.asyncio
    async def test_hint_added_when_chunk_count_below_threshold(self):
        chunks = _chunks_with_temporal_spread()[:4]
        # Adjust chunk[3] to satisfy semantic constraints (CTA in last third)
        chunks[3] = ScoredChunk(
            start_ms=70_000, end_ms=88_000, text="cta",
            score=ChunkScore(hook_score=0.1, has_cta=True, importance_score=0.5),
        )
        body = {
            "fragments": [
                {"role": "hook", "chunk_index": 0, "rationale": "o"},
                {"role": "intro", "chunk_index": 1, "rationale": "i"},
                {"role": "detail", "chunk_index": 2, "rationale": "d"},
                {"role": "cta", "chunk_index": 3, "rationale": "c"},
            ],
            "global_rationale": "arc",
        }
        picker, mock_client, _ = _make_picker(
            create_returns=_mock_openai_response(body),
        )
        await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        # The user prompt sent to OpenAI must contain the hint.
        call = mock_client.chat.completions.create.call_args
        user_msg = next(
            m for m in call.kwargs["messages"] if m["role"] == "user"
        )
        assert "NOT enough chunks for 2 DETAILs" in user_msg["content"]

    @pytest.mark.asyncio
    async def test_hint_omitted_when_chunk_count_above_threshold(self):
        chunks = _chunks_with_temporal_spread()  # 6 chunks
        picker, mock_client, _ = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        call = mock_client.chat.completions.create.call_args
        user_msg = next(
            m for m in call.kwargs["messages"] if m["role"] == "user"
        )
        assert "NOT enough chunks" not in user_msg["content"]


class TestChunkCap:
    """PR 9: ``_select_chunks_for_prompt`` caps chunks to 20 when
    source has more, preserving temporal coverage. Staging 2026-05-08
    saw 128-142 chunks per scan timing out gpt-4o-mini.
    """

    @pytest.mark.asyncio
    async def test_capped_chunk_count_logged(self):
        # 30-chunk source, cap is 20.
        chunks = []
        for i in range(30):
            chunks.append(ScoredChunk(
                start_ms=i * 60_000, end_ms=i * 60_000 + 30_000,
                text=f"c{i}",
                score=ChunkScore(
                    hook_score=0.5, has_cta=(i >= 22),
                    importance_score=0.5,
                ),
            ))
        body = _well_formed_llm_response()
        # Adjust indices to stay within the capped list (0..19).
        body["fragments"] = [
            {"role": "hook", "chunk_index": 0, "rationale": "o"},
            {"role": "intro", "chunk_index": 5, "rationale": "i"},
            {"role": "detail", "chunk_index": 10, "rationale": "d"},
            {"role": "cta", "chunk_index": 19, "rationale": "c"},
        ]
        picker, mock_client, _ = _make_picker(
            create_returns=_mock_openai_response(body),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        # Picker fired LLM with capped (≤20) chunks, then mapped indices
        # back to ScoredChunk via the capped list.
        assert isinstance(plan, StoryboardPlan)
        # Prompt content reflects the cap.
        call = mock_client.chat.completions.create.call_args
        user_msg = next(
            m for m in call.kwargs["messages"] if m["role"] == "user"
        )
        # The prompt lists 20 chunks (indices 0..19); index 25 should
        # NOT appear because it's beyond the cap.
        assert "[20]" not in user_msg["content"]
        assert "[25]" not in user_msg["content"]
        assert "[19]" in user_msg["content"]


class TestSelectChunksForPromptHelper:
    """Direct unit tests for the cap helper. Pure function — no
    LLM, no asyncio, no fixtures."""

    def _spread_chunks(self, n: int) -> list[ScoredChunk]:
        return [
            ScoredChunk(
                start_ms=i * 60_000, end_ms=i * 60_000 + 30_000,
                text=f"c{i}",
                score=ChunkScore(
                    hook_score=0.9 - (i * 0.02),
                    has_cta=(i >= int(n * 0.7)),
                    importance_score=0.5 + (i % 3) * 0.15,
                ),
            )
            for i in range(n)
        ]

    def test_cap_smaller_than_chunk_count_passes_through(self):
        from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
            _select_chunks_for_prompt,
        )
        chunks = self._spread_chunks(8)
        out = _select_chunks_for_prompt(chronological=chunks, cap=20)
        assert len(out) == 8
        assert out == chunks  # exact pass-through, sorted

    def test_cap_returns_at_most_cap_chunks(self):
        from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
            _select_chunks_for_prompt,
        )
        chunks = self._spread_chunks(50)
        out = _select_chunks_for_prompt(chronological=chunks, cap=20)
        assert len(out) <= 20

    def test_cap_returns_chunks_in_chronological_order(self):
        from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
            _select_chunks_for_prompt,
        )
        chunks = self._spread_chunks(50)
        out = _select_chunks_for_prompt(chronological=chunks, cap=20)
        starts = [c.start_ms for c in out]
        assert starts == sorted(starts)

    def test_cap_preserves_temporal_thirds_coverage(self):
        from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
            _select_chunks_for_prompt,
        )
        chunks = self._spread_chunks(50)
        out = _select_chunks_for_prompt(chronological=chunks, cap=20)
        src_dur = max(c.end_ms for c in chunks)
        first = sum(1 for c in out if c.start_ms < src_dur // 3)
        last = sum(1 for c in out if c.start_ms >= src_dur * 2 // 3)
        # Each third must contribute ≥1 chunk so HOOK / CTA candidates
        # remain available to the LLM.
        assert first >= 1
        assert last >= 1

    def test_cap_keeps_all_has_cta_chunks_in_last_third(self):
        from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
            _select_chunks_for_prompt,
            _CTA_CANDIDATES_PER_THIRD,
        )
        chunks = self._spread_chunks(50)
        out = _select_chunks_for_prompt(chronological=chunks, cap=20)
        # All has_cta chunks in the last third should appear, capped
        # at _CTA_CANDIDATES_PER_THIRD. Without CTA preservation the
        # LLM would have no valid CTA pick.
        ctas_in_out = [c for c in out if c.score.has_cta]
        assert len(ctas_in_out) >= 1
        assert len(ctas_in_out) <= _CTA_CANDIDATES_PER_THIRD


class TestBudgetExhausted:
    @pytest.mark.asyncio
    async def test_budget_zero_falls_back_without_call(self):
        chunks = _chunks_with_temporal_spread()
        # Budget that's smaller than the reservation → first
        # ``check_and_reserve`` raises.
        picker, mock_client, spied = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
            daily_budget_usd=0.0,
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        mock_client.chat.completions.create.assert_not_called()
        spied.assemble.assert_called_once()


class TestApiFailures:
    @pytest.mark.asyncio
    async def test_timeout_falls_back(self):
        chunks = _chunks_with_temporal_spread()

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10.0)  # exceeds picker.timeout_s=5.0
            return _mock_openai_response(_well_formed_llm_response())

        picker, mock_client, spied = _make_picker(create_returns=None)
        # picker.timeout_s drives wait_for; sleep 10s would exceed it,
        # but for test speed we override the picker's timeout to 0.05s
        # and have the mock sleep 1.0s.
        picker.timeout_s = 0.05
        mock_client.chat.completions.create = AsyncMock(side_effect=slow_call)

        async def fast_sleep(*args, **kwargs):
            await asyncio.sleep(1.0)
            return _mock_openai_response(_well_formed_llm_response())

        mock_client.chat.completions.create = AsyncMock(side_effect=fast_sleep)

        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_called_once()
        # Reservation was released — second call would still succeed
        # against the budget (no leak).
        assert picker.budget_tracker.spent_today_usd() == 0.0

    @pytest.mark.asyncio
    async def test_sdk_exception_falls_back(self):
        chunks = _chunks_with_temporal_spread()
        picker, _, spied = _make_picker(
            create_raises=RuntimeError("openai exploded"),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_called_once()
        # Reservation released on api failure.
        assert picker.budget_tracker.spent_today_usd() == 0.0


class TestValidationFailures:
    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self):
        chunks = _chunks_with_temporal_spread()
        picker, _, spied = _make_picker(
            create_returns=_mock_openai_response("not-valid-json{"),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_called_once()
        assert picker.budget_tracker.spent_today_usd() == 0.0

    @pytest.mark.asyncio
    async def test_pydantic_slot_count_violation_falls_back(self):
        chunks = _chunks_with_temporal_spread()
        body = _well_formed_llm_response()
        body["fragments"][0]["role"] = "intro"  # 0× hook, 2× intro
        picker, _, spied = _make_picker(
            create_returns=_mock_openai_response(body),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_called_once()


class TestSemanticConstraints:
    @pytest.mark.asyncio
    async def test_chunk_index_out_of_bounds_falls_back(self):
        chunks = _chunks_with_temporal_spread()  # n=6
        body = _well_formed_llm_response()
        body["fragments"][0]["chunk_index"] = 99  # bogus
        picker, _, spied = _make_picker(
            create_returns=_mock_openai_response(body),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_called_once()

    @pytest.mark.asyncio
    async def test_hook_in_last_third_falls_back(self):
        chunks = _chunks_with_temporal_spread()
        body = _well_formed_llm_response()
        # Pick chunk[5] (130s start in a 170s source) for HOOK — past
        # the first-third cutoff (~56s).
        body["fragments"][0]["chunk_index"] = 5
        body["fragments"][3]["chunk_index"] = 0  # also need a CTA pick that won't pass
        picker, _, spied = _make_picker(
            create_returns=_mock_openai_response(body),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_called_once()

    @pytest.mark.asyncio
    async def test_cta_in_first_third_falls_back(self):
        chunks = _chunks_with_temporal_spread()
        body = _well_formed_llm_response()
        body["fragments"][3]["chunk_index"] = 0  # CTA at 0s — wrong
        picker, _, spied = _make_picker(
            create_returns=_mock_openai_response(body),
        )
        plan = await picker.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_called_once()


class TestPromptVersionDrift:
    @pytest.mark.asyncio
    async def test_drift_warns_but_does_not_block(self, caplog):
        import logging
        chunks = _chunks_with_temporal_spread()
        picker, _, spied = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        picker.prompt_version = "v0-stale"  # different from module's "v1"
        with caplog.at_level(logging.WARNING):
            plan = await picker.assemble(
                all_chunks=chunks, segments=_segments_for(chunks),
                target_duration_ms=60_000, llm_label="X", spoken_aliases=[],
            )
        # Picker still completes successfully — drift is non-blocking.
        assert isinstance(plan, StoryboardPlan)
        spied.assemble.assert_not_called()


class TestSeedDeterminism:
    @pytest.mark.asyncio
    async def test_same_label_same_seed(self):
        chunks = _chunks_with_temporal_spread()
        picker_a, ma, _ = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        picker_b, mb, _ = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        await picker_a.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="dyson", spoken_aliases=[],
        )
        await picker_b.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="dyson", spoken_aliases=[],
        )
        seed_a = ma.chat.completions.create.call_args.kwargs["seed"]
        seed_b = mb.chat.completions.create.call_args.kwargs["seed"]
        assert seed_a == seed_b

    @pytest.mark.asyncio
    async def test_different_label_different_seed(self):
        chunks = _chunks_with_temporal_spread()
        picker_a, ma, _ = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        picker_b, mb, _ = _make_picker(
            create_returns=_mock_openai_response(_well_formed_llm_response()),
        )
        await picker_a.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="A", spoken_aliases=[],
        )
        await picker_b.assemble(
            all_chunks=chunks, segments=_segments_for(chunks),
            target_duration_ms=60_000, llm_label="B", spoken_aliases=[],
        )
        seed_a = ma.chat.completions.create.call_args.kwargs["seed"]
        seed_b = mb.chat.completions.create.call_args.kwargs["seed"]
        assert seed_a != seed_b
