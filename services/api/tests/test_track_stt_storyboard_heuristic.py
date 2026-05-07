"""Unit tests for ``HeuristicStoryboardPicker`` (Tier B).

Pure-function tests over synthetic ``ScoredChunk`` fixtures. Cover:

* All four slot fillers — HOOK, INTRO, DETAIL, CTA — independently
* Edge cases: empty chunks, single segment, no CTA, no INTRO match
* Determinism: same input → same output, ties broken by start_ms
* Storyboard ordering invariants (HOOK first, CTA last by role)
* Used-set: same chunk never fills two slots
* Slot-budget clamping: fragment ranges never exceed the budget
* Korean label/alias matching for INTRO selection

Future Tier C tests will sit in a sibling file
``test_track_stt_storyboard_llm.py`` and assert mocked OpenAI
contracts — the Protocol contract here stays the regression gate.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionedScene,
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard import (
    SLOT_ORDER,
    HeuristicStoryboardPicker,
    SlotBudgets,
    SlotRole,
    StoryboardPlan,
)


# ---------- helpers ----------


def _scene(start_ms: int, end_ms: int, sid: str = "s") -> MentionedScene:
    return MentionedScene(
        scene_id=sid,
        start_ms=start_ms,
        end_ms=end_ms,
        score=1.0,
        matched_field="transcript_raw",
        matched_aliases=[],
        transcript_text=f"transcript at {start_ms}",
    )


def _seg(
    start_ms: int, end_ms: int, scenes: list[MentionedScene] | None = None,
) -> MentionSegment:
    return MentionSegment(
        start_ms=start_ms,
        end_ms=end_ms,
        scenes=scenes or [_scene(start_ms, end_ms)],
    )


def _chunk(
    start_ms: int,
    end_ms: int,
    *,
    text: str = "",
    hook: float = 0.5,
    importance: float = 0.5,
    cta: bool = False,
) -> ScoredChunk:
    return ScoredChunk(
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        score=ChunkScore(
            hook_score=hook,
            has_cta=cta,
            importance_score=importance,
        ),
    )


def _picker(**budget_overrides) -> HeuristicStoryboardPicker:
    return HeuristicStoryboardPicker(budgets=SlotBudgets(**budget_overrides))


# ---------- empty / degenerate inputs ----------


class TestEmptyInputs:
    @pytest.mark.asyncio
    async def test_empty_chunks_returns_empty_plan(self) -> None:
        plan = await _picker().assemble(
            all_chunks=[], segments=[_seg(0, 30_000)],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        assert isinstance(plan, StoryboardPlan)
        assert plan.fragments == []
        assert plan.slots_filled == set()
        assert "empty_input" in plan.fallbacks_used
        assert plan.is_empty is True

    @pytest.mark.asyncio
    async def test_empty_segments_returns_empty_plan(self) -> None:
        # Defensive: chunks without segments shouldn't happen in
        # production (segments produce chunks) but the picker must
        # not crash if it does.
        plan = await _picker().assemble(
            all_chunks=[_chunk(0, 20_000)],
            segments=[],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        assert plan.is_empty
        assert "empty_input" in plan.fallbacks_used


# ---------- HOOK slot ----------


class TestHookSlot:
    @pytest.mark.asyncio
    async def test_hook_picks_max_hook_score_in_first_segment(self) -> None:
        seg = _seg(0, 60_000)
        chunks = [
            _chunk(0, 20_000, hook=0.4, importance=0.5),
            _chunk(20_000, 40_000, hook=0.95, importance=0.5),  # winner
            _chunk(40_000, 60_000, hook=0.3, importance=0.5),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        hook = next((f for f in plan.fragments if f.role == SlotRole.HOOK), None)
        assert hook is not None
        assert hook.source_start_ms == 20_000
        # Default HOOK budget is 8s; chunk is 20s → clamped to 8s.
        assert hook.actual_duration_ms == 8_000
        assert "max_hook_score=0.95" in hook.rationale

    @pytest.mark.asyncio
    async def test_hook_only_considers_first_segment_chunks(self) -> None:
        # Higher hook in segment 2 must NOT win — HOOK belongs in
        # the opening third of the source video.
        seg_a = _seg(0, 30_000)
        seg_b = _seg(60_000, 90_000)
        chunks = [
            _chunk(0, 20_000, hook=0.5),       # in seg_a
            _chunk(60_000, 80_000, hook=0.99), # in seg_b — must NOT be HOOK
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg_a, seg_b],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        hook = next((f for f in plan.fragments if f.role == SlotRole.HOOK), None)
        assert hook is not None
        assert hook.source_start_ms == 0


# ---------- INTRO slot ----------


class TestIntroSlot:
    @pytest.mark.asyncio
    async def test_intro_picks_first_label_match_above_floor(self) -> None:
        seg = _seg(0, 60_000)
        chunks = [
            _chunk(0, 20_000, text="other content", importance=0.7),
            _chunk(20_000, 40_000, text="달심 제품 소개", importance=0.7),  # winner
            _chunk(40_000, 60_000, text="달심 너무 좋아요", importance=0.9),  # later
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        intro = next((f for f in plan.fragments if f.role == SlotRole.INTRO), None)
        assert intro is not None
        assert intro.source_start_ms == 20_000

    @pytest.mark.asyncio
    async def test_intro_matches_alias_when_label_missing(self) -> None:
        seg = _seg(0, 60_000)
        chunks = [
            _chunk(0, 20_000, text="other thing", importance=0.7),
            _chunk(20_000, 40_000, text="이 주스 정말 맛있어요", importance=0.7),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=["이 주스"],
        )
        intro = next((f for f in plan.fragments if f.role == SlotRole.INTRO), None)
        assert intro is not None
        assert intro.source_start_ms == 20_000

    @pytest.mark.asyncio
    async def test_intro_lowers_importance_floor_when_no_match(self) -> None:
        # The label-matching chunk has below-floor importance. The
        # picker must drop the floor and pick it anyway, with the
        # ``intro_low_importance`` telemetry marker. HOOK's chunk is
        # placed at the start with a strong hook score so it's
        # claimed by HOOK before INTRO runs (otherwise HOOK would
        # consume the label-matching chunk and INTRO would find
        # nothing — separate failure mode covered by
        # ``test_intro_skipped_when_no_label_match_anywhere``).
        seg = _seg(0, 60_000)
        chunks = [
            _chunk(0, 20_000, text="strong opener", hook=0.95, importance=0.5),
            _chunk(20_000, 40_000, text="달심 첫 등장", importance=0.4),
            _chunk(40_000, 60_000, text="other", importance=0.9),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        intro = next((f for f in plan.fragments if f.role == SlotRole.INTRO), None)
        assert intro is not None
        assert intro.source_start_ms == 20_000
        assert "intro_low_importance" in plan.fallbacks_used

    @pytest.mark.asyncio
    async def test_intro_skipped_when_no_label_match_anywhere(self) -> None:
        seg = _seg(0, 60_000)
        chunks = [
            _chunk(0, 20_000, text="generic banter", importance=0.9, hook=0.9),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        # The single chunk fills HOOK; INTRO has nothing to match.
        assert SlotRole.INTRO not in plan.slots_filled
        assert "no_intro_candidate" in plan.fallbacks_used


# ---------- CTA slot ----------


class TestCtaSlot:
    @pytest.mark.asyncio
    async def test_cta_picks_explicit_cta_chunk_in_latest_segment(self) -> None:
        seg_early = _seg(0, 30_000)
        seg_late = _seg(60_000, 90_000)
        chunks = [
            _chunk(0, 20_000, text="open"),
            _chunk(60_000, 80_000, text="middle", cta=False),
            _chunk(80_000, 90_000, text="지금 구매", cta=True),  # winner
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg_early, seg_late],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        cta = next((f for f in plan.fragments if f.role == SlotRole.CTA), None)
        assert cta is not None
        assert cta.source_start_ms == 80_000
        assert cta.rationale == "has_cta_latest"

    @pytest.mark.asyncio
    async def test_cta_falls_back_to_max_hook_in_tail_when_no_explicit(self) -> None:
        seg = _seg(0, 60_000)
        chunks = [
            _chunk(0, 20_000, hook=0.99, cta=False),     # not in tail
            _chunk(20_000, 40_000, hook=0.3, cta=False), # tail starts here
            _chunk(40_000, 60_000, hook=0.85, cta=False),  # tail max-hook
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        cta = next((f for f in plan.fragments if f.role == SlotRole.CTA), None)
        assert cta is not None
        assert cta.source_start_ms == 40_000
        assert "cta_no_explicit_picks_tail_max_hook" in plan.fallbacks_used

    @pytest.mark.asyncio
    async def test_cta_skipped_when_only_chunk_used_by_hook(self) -> None:
        # Single chunk → HOOK takes it. Nothing left for CTA.
        seg = _seg(0, 60_000)
        chunks = [_chunk(0, 20_000, hook=0.9)]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        assert SlotRole.CTA not in plan.slots_filled
        assert "no_cta_candidate" in plan.fallbacks_used


# ---------- DETAIL slot ----------


class TestDetailSlot:
    @pytest.mark.asyncio
    async def test_detail_picks_top_importance_chunks_chronologically(self) -> None:
        seg = _seg(0, 120_000)
        chunks = [
            _chunk(0, 20_000, text="hook", hook=0.99),  # used by HOOK
            _chunk(20_000, 40_000, importance=0.7),
            _chunk(40_000, 60_000, importance=0.95),     # detail #1
            _chunk(60_000, 80_000, importance=0.85),     # detail #2
            _chunk(80_000, 100_000, importance=0.5),
            _chunk(100_000, 120_000, cta=True, hook=0.4),  # used by CTA
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        details = [f for f in plan.fragments if f.role == SlotRole.DETAIL]
        assert len(details) == 2
        # Chronologically ordered, even though sort-by-importance
        # would produce ``[40k, 60k]`` already.
        assert details[0].source_start_ms == 40_000
        assert details[1].source_start_ms == 60_000

    @pytest.mark.asyncio
    async def test_detail_max_two_fragments_cap(self) -> None:
        seg = _seg(0, 200_000)
        chunks = [_chunk(0, 20_000, hook=0.99)]  # HOOK
        # 5 high-importance candidates; cap should select only 2.
        for i, start in enumerate([20_000, 40_000, 60_000, 80_000, 100_000]):
            chunks.append(_chunk(start, start + 20_000, importance=0.9 - i * 0.01))
        chunks.append(_chunk(180_000, 200_000, cta=True))  # CTA
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        details = [f for f in plan.fragments if f.role == SlotRole.DETAIL]
        assert len(details) == 2

    @pytest.mark.asyncio
    async def test_detail_budget_split_evenly(self) -> None:
        # Default DETAIL budget = 25_000ms / 2 detail fragments =
        # 12_500ms per fragment.
        seg = _seg(0, 100_000)
        chunks = [
            _chunk(0, 20_000, hook=0.99),
            _chunk(20_000, 40_000, importance=0.9),
            _chunk(40_000, 60_000, importance=0.85),
            _chunk(80_000, 100_000, cta=True),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        details = [f for f in plan.fragments if f.role == SlotRole.DETAIL]
        assert len(details) == 2
        for d in details:
            # Each chunk is 20s but the budget per fragment is 12.5s
            # → fragment clamped to 12.5s.
            assert d.actual_duration_ms == 12_500


# ---------- storyboard ordering + invariants ----------


class TestStoryboardOrderingInvariants:
    @pytest.mark.asyncio
    async def test_fragments_sorted_into_storyboard_order(self) -> None:
        seg = _seg(0, 100_000)
        chunks = [
            _chunk(0, 20_000, text="달심 hook", hook=0.9, importance=0.7),
            _chunk(40_000, 60_000, importance=0.95),
            _chunk(80_000, 100_000, text="지금 구매", cta=True),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        roles = [f.role for f in plan.fragments]
        # HOOK first, CTA last; INTRO/DETAIL between.
        # SLOT_ORDER ranks them; ascending order is canonical.
        for i in range(1, len(roles)):
            assert SLOT_ORDER[roles[i - 1]] <= SLOT_ORDER[roles[i]]

    @pytest.mark.asyncio
    async def test_no_chunk_fills_two_slots(self) -> None:
        # Single chunk that COULD theoretically fill HOOK + INTRO +
        # CTA all by itself; used-set must prevent reuse.
        seg = _seg(0, 30_000)
        chunks = [
            _chunk(0, 20_000, text="달심 great", hook=0.99, importance=0.99, cta=True),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        # Only one fragment emitted — the single chunk fills HOOK.
        assert len(plan.fragments) == 1
        assert plan.fragments[0].role == SlotRole.HOOK

    @pytest.mark.asyncio
    async def test_total_duration_within_target(self) -> None:
        seg = _seg(0, 200_000)
        chunks = [
            _chunk(0, 20_000, hook=0.99),
            _chunk(20_000, 40_000, text="달심", importance=0.7),
            _chunk(40_000, 60_000, importance=0.95),
            _chunk(60_000, 80_000, importance=0.85),
            _chunk(180_000, 200_000, cta=True),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        # Default budgets sum to 53_000ms; tolerance is target +
        # MAX overshoot. We assert just ≤ target which is the tight
        # bound after slot clamping.
        assert plan.total_duration_ms <= 60_000

    @pytest.mark.asyncio
    async def test_fragments_no_overlap_in_source_time(self) -> None:
        seg = _seg(0, 100_000)
        chunks = [
            _chunk(0, 20_000, hook=0.9, text="달심"),
            _chunk(20_000, 40_000, importance=0.95),
            _chunk(40_000, 60_000, importance=0.85),
            _chunk(80_000, 100_000, cta=True),
        ]
        plan = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        # All fragments come from distinct chunks (used-set), so
        # source ranges must not overlap.
        ranges = sorted(
            [(f.source_start_ms, f.source_end_ms) for f in plan.fragments],
        )
        for i in range(1, len(ranges)):
            prev_end = ranges[i - 1][1]
            cur_start = ranges[i][0]
            assert cur_start >= prev_end, (
                f"fragment overlap detected: {ranges[i - 1]} → {ranges[i]}"
            )

    @pytest.mark.asyncio
    async def test_determinism_same_input_same_output(self) -> None:
        seg = _seg(0, 100_000)
        chunks = [
            _chunk(0, 20_000, hook=0.9, text="달심", importance=0.7),
            _chunk(20_000, 40_000, importance=0.95),
            _chunk(80_000, 100_000, cta=True),
        ]
        plan_a = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        plan_b = await _picker().assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        assert plan_a.fragments == plan_b.fragments


# ---------- slot budget overrides ----------


class TestSlotBudgets:
    @pytest.mark.asyncio
    async def test_custom_budgets_clamp_fragment_durations(self) -> None:
        seg = _seg(0, 100_000)
        chunks = [
            _chunk(0, 30_000, hook=0.9),
            _chunk(80_000, 100_000, cta=True),
        ]
        # Tiny HOOK, large CTA budget.
        picker = _picker(hook_ms=3_000, cta_ms=15_000)
        plan = await picker.assemble(
            all_chunks=chunks, segments=[seg],
            target_duration_ms=60_000,
            llm_label="달심", spoken_aliases=[],
        )
        hook = next(f for f in plan.fragments if f.role == SlotRole.HOOK)
        cta = next(f for f in plan.fragments if f.role == SlotRole.CTA)
        assert hook.actual_duration_ms == 3_000
        # CTA chunk is 20s; budget is 15s → clamped to 15s.
        assert cta.actual_duration_ms == 15_000
