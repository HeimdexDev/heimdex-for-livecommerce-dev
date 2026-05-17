"""Targeted tests for :class:`OpenAIPicker` failure-fallback paths.

The full happy-path is covered indirectly via the F4 integration
suite; this module focuses on the failure modes that motivated the
fallback wiring:

* timeout / 5xx → fall back
* empty / out-of-range / oversize selection → fall back

The oversize test specifically pins the Codex P2 fix: when GPT
ignores the duration budget rule (e.g. picks one long window for a
30s preset), we must NOT pass the oversize set to the lib's
``select_subset`` — that trims by dropping low-score windows and
can leave ``selected=[]`` even though shorter candidates existed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from heimdex_media_pipelines.product_track.alignment import AnnotatedWindow
from heimdex_media_pipelines.product_track.config import TrackingConfig
from heimdex_media_pipelines.product_track.subset_selector import ScoredWindow

from src.openai_picker import OpenAIPicker


def _make_window(
    *,
    scene_id: str,
    start_ms: int,
    end_ms: int,
    score: float = 0.8,
) -> ScoredWindow:
    annotated = AnnotatedWindow(
        scene_id=scene_id,
        window_start_ms=start_ms,
        window_end_ms=end_ms,
        avg_bbox_area_pct=0.1,
        avg_confidence=0.85,
        peak_confidence=0.9,
        frame_count=10,
        rejected_reason=None,
        has_narration_mention=False,
        has_ocr_overlap=False,
    )
    return ScoredWindow(
        window=annotated,
        composite_score=score,
        score_components={
            "prominence": 0.3,
            "narration": 0.0,
            "ocr": 0.0,
            "duration_fitness": 0.5,
            "spread_bonus": 0.0,
        },
    )


def test_picker_falls_back_when_llm_pick_exceeds_duration_budget():
    """GPT picks a single 60-second window for a 30-second preset
    (well past the 1.05× overshoot factor). Pre-fix the picker
    returned that window, ``select_subset`` later dropped it as
    oversize, ``selected=[]`` and the whole job failed. Post-fix
    the picker validates the total duration and falls back to
    GreedyPicker, which honors the budget structurally."""
    candidates = [
        _make_window(scene_id="s1", start_ms=0, end_ms=60_000, score=0.95),
        _make_window(scene_id="s2", start_ms=60_000, end_ms=70_000, score=0.6),
        _make_window(scene_id="s3", start_ms=80_000, end_ms=90_000, score=0.55),
    ]

    fake_client = MagicMock()
    picker = OpenAIPicker(client=fake_client, model="gpt-4o-mini")

    # _call_llm returns the index of the 60s window — way over a 30s
    # preset (30 * 1.05 = 31.5s budget).
    with patch.object(picker, "_call_llm", return_value=[0]):
        result = picker.pick(
            candidates,
            duration_preset_sec=30,
            config=TrackingConfig(),
        )

    # GreedyPicker would pick s2 + s3 (sum 20s) under budget. The
    # exact picks depend on the greedy impl, but the result MUST NOT
    # be the oversize [s1] choice.
    selected_scene_ids = [s.window.scene_id for s in result]
    assert "s1" not in selected_scene_ids or len(selected_scene_ids) > 1
    # And the result MUST fit the budget.
    total_ms = sum(s.window.duration_ms for s in result)
    assert total_ms <= int(30 * 1000 * 1.05)


def test_picker_returns_llm_pick_when_within_budget():
    """Sanity: when GPT's pick respects the duration budget, the
    picker returns it as-is (no fallback)."""
    candidates = [
        _make_window(scene_id="s1", start_ms=0, end_ms=10_000, score=0.95),
        _make_window(scene_id="s2", start_ms=20_000, end_ms=30_000, score=0.85),
        _make_window(scene_id="s3", start_ms=40_000, end_ms=80_000, score=0.4),
    ]

    fake_client = MagicMock()
    picker = OpenAIPicker(client=fake_client, model="gpt-4o-mini")

    # 10s + 10s = 20s, well under a 30s preset.
    with patch.object(picker, "_call_llm", return_value=[0, 1]):
        result = picker.pick(
            candidates,
            duration_preset_sec=30,
            config=TrackingConfig(),
        )

    assert [s.window.scene_id for s in result] == ["s1", "s2"]


def test_picker_accumulates_cost_from_response_usage():
    """Pre-fix the picker dropped ``resp.usage`` and ``total_cost_usd``
    stayed at 0, so every track job using the LLM picker reported $0
    to the api's daily-budget gate. Post-fix the call cost is
    computed from input/output tokens at gpt-4o-mini pricing and
    accumulated across pick() calls."""
    candidates = [
        _make_window(scene_id="s1", start_ms=0, end_ms=10_000, score=0.9),
        _make_window(scene_id="s2", start_ms=20_000, end_ms=30_000, score=0.8),
    ]

    fake_response = MagicMock()
    fake_response.choices = [MagicMock()]
    fake_response.choices[0].message.content = '{"selected_indices": [0, 1]}'
    fake_response.usage = MagicMock(
        prompt_tokens=1000,
        completion_tokens=500,
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    picker = OpenAIPicker(client=fake_client, model="gpt-4o-mini")
    assert picker.total_cost_usd == 0

    picker.pick(
        candidates,
        duration_preset_sec=30,
        config=TrackingConfig(),
    )

    # 1000 input * $0.15 / 1M + 500 output * $0.60 / 1M
    #   = 0.00015 + 0.00030 = 0.00045
    from decimal import Decimal
    expected = Decimal("0.00015") + Decimal("0.00030")
    assert picker.total_cost_usd == expected

    # Second call accumulates instead of overwriting.
    picker.pick(
        candidates,
        duration_preset_sec=30,
        config=TrackingConfig(),
    )
    assert picker.total_cost_usd == expected * 2


def test_picker_falls_back_on_call_failure():
    """Existing fallback path — pinned here so future refactors
    don't accidentally regress it."""
    candidates = [
        _make_window(scene_id="s1", start_ms=0, end_ms=10_000, score=0.9),
        _make_window(scene_id="s2", start_ms=20_000, end_ms=30_000, score=0.8),
    ]

    fake_client = MagicMock()
    picker = OpenAIPicker(client=fake_client, model="gpt-4o-mini")

    with patch.object(picker, "_call_llm", side_effect=RuntimeError("openai 503")):
        result = picker.pick(
            candidates,
            duration_preset_sec=30,
            config=TrackingConfig(),
        )

    # GreedyPicker returns something; assert at least one window.
    assert len(result) > 0
