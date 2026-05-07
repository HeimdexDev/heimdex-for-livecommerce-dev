"""Tests for the Tier C user-prompt builder.

Plan: ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md`` PR 4.

Pure-function tests. No OpenAI calls, no I/O.
"""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard.llm_prompt import (
    PROMPT_VERSION,
    _SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    SlotBudgets,
)


def _make_chunk(start_ms: int, end_ms: int, *, hook=0.5, has_cta=False, importance=0.5, text="hi"):
    return ScoredChunk(
        start_ms=start_ms, end_ms=end_ms, text=text,
        score=ChunkScore(hook_score=hook, has_cta=has_cta, importance_score=importance),
    )


class TestPromptVersion:
    def test_module_constant_exists(self):
        # Bumped v1 → v2 in PR 9 (chunk-cap + small-chunk hint —
        # changes prompt input shape, eval cache invalidates).
        assert PROMPT_VERSION == "v2"

    def test_system_prompt_non_empty(self):
        assert len(_SYSTEM_PROMPT) > 100
        # Must mention all 4 slots so the LLM knows the shape it's
        # filling. Lower-cased substring check survives prompt edits
        # that re-format whitespace.
        low = _SYSTEM_PROMPT.lower()
        assert "hook" in low and "intro" in low and "detail" in low and "cta" in low


class TestTimeFormatting:
    """Regression for the mm:ss bug found 2026-05-07 (mistakes log)."""

    def test_short_chunk_formats_correctly(self):
        # 0-12000ms → 00:00-00:12 (NOT 00:00-12:12).
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 12_000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        assert "[0] 00:00-00:12" in out
        assert "12:12" not in out  # the bug shape

    def test_minute_chunk_formats_correctly(self):
        # 240000ms (4:00) - 255000ms (4:15)
        out = build_user_prompt(
            all_chunks=[_make_chunk(240_000, 255_000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        assert "[0] 04:00-04:15" in out
        assert "240:00" not in out  # the bug shape

    def test_chunks_listed_chronologically(self):
        # Input order is reversed; output must be sorted by start_ms.
        out = build_user_prompt(
            all_chunks=[
                _make_chunk(60_000, 75_000, text="late"),
                _make_chunk(0, 15_000, text="early"),
            ],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        # "early" (start_ms=0) must appear in the [0] line; "late" in [1].
        idx_0_line = next(L for L in out.splitlines() if L.startswith("[0]"))
        idx_1_line = next(L for L in out.splitlines() if L.startswith("[1]"))
        assert "early" in idx_0_line
        assert "late" in idx_1_line


class TestProductLine:
    def test_with_aliases(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000)],
            target_duration_ms=60_000,
            llm_label="다이슨 헤어드라이어",
            spoken_aliases=["다이슨", "dyson", "드라이기"],
            slot_budgets=SlotBudgets(),
        )
        assert "다이슨 헤어드라이어" in out
        assert "다이슨, dyson, 드라이기" in out

    def test_no_aliases(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        # No "(also called: ...)" suffix when aliases empty.
        assert "(also called" not in out

    def test_aliases_with_blanks_filtered(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=["a", "", "  ", "b"],
            slot_budgets=SlotBudgets(),
        )
        assert "(also called: a, b)" in out


class TestScoreLine:
    def test_includes_all_three_features(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000, hook=0.71, has_cta=True, importance=0.42)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        # Compact format — exactly the LLM-anchor numerics.
        assert "importance=0.42" in out
        assert "hook=0.71" in out
        assert "has_cta=true" in out


class TestTextHandling:
    def test_long_text_truncated(self):
        long = "x" * 800
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000, text=long)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        # 600 char cap + ellipsis.
        assert "x" * 600 + "…" in out
        assert "x" * 700 not in out

    def test_newlines_collapsed_to_spaces(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000, text="a\nb\nc")],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        assert "\"a b c\"" in out
        # Defense against accidental multi-line chunk blowing up indexing.
        chunk_section = out.split("Chunks (chronological")[1]
        assert chunk_section.count("[0]") == 1


class TestSlotBudgetLine:
    def test_uses_seconds_format(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(hook_ms=8000, intro_ms=12000, detail_ms=25000, cta_ms=8000),
        )
        assert "HOOK=8s" in out
        assert "INTRO=12s" in out
        assert "DETAIL=25s" in out
        assert "CTA=8s" in out


class TestEmptyInput:
    def test_zero_chunks_still_produces_prompt(self):
        # Picker filters empty input upstream, but the prompt builder
        # itself shouldn't crash on it.
        out = build_user_prompt(
            all_chunks=[],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        assert "Product: X" in out
        assert "Chunks (chronological, 0-indexed):" in out


class TestSmallChunkHint:
    """v2 hint nudges the LLM toward 1× DETAIL when chunk_count
    is just-enough for unique fills — staging 2026-05-08 saw 2×
    DETAIL picked on 4-chunk inputs which forced chunk_index reuse
    and Pydantic-rejected the response.
    """

    def test_hint_omitted_by_default(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
        )
        assert "NOT enough" not in out
        assert "Use exactly 1 DETAIL" not in out

    def test_hint_included_when_flag_set(self):
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
            small_chunk_hint=True,
        )
        # Both phrases appear — keep the test resilient to minor copy
        # tweaks but lock in the substantive message.
        assert "NOT enough chunks for 2 DETAILs" in out
        assert "Use exactly 1 DETAIL" in out

    def test_hint_appears_before_chunk_listing(self):
        # Hint must be visible to the LLM before it sees the chunks
        # so it can plan accordingly.
        out = build_user_prompt(
            all_chunks=[_make_chunk(0, 1000)],
            target_duration_ms=60_000,
            llm_label="X",
            spoken_aliases=[],
            slot_budgets=SlotBudgets(),
            small_chunk_hint=True,
        )
        hint_idx = out.find("Use exactly 1 DETAIL")
        chunks_idx = out.find("Chunks (chronological")
        assert 0 <= hint_idx < chunks_idx
