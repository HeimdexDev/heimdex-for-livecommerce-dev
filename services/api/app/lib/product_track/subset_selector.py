# VENDORED from heimdex-media-pipelines v0.12.3 (5d82c7d).
# See app/lib/product_track/__init__.py for the sync ritual.
"""Subset selection — pick which appearance windows make the final clip.

Two-step:

  1. :func:`score_windows` — pure function that assigns a composite
     score per accepted window using the plan §6.2 step 7 weights.
  2. :func:`select_subset` — calls a :class:`SubsetPicker` (Protocol;
     gpt-4o-mini-backed in prod, deterministic-greedy in tests) to
     pick the subset that fits the duration target.

Splitting this in two lets the LLM see scores it can reason about
without re-deriving them, and lets tests skip the LLM entirely.

The scorer is deterministic — same inputs → same scores. The picker
may be non-deterministic (LLM call); the API persists the picker
version so a re-pick can be reproduced if the model is the same.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.lib.product_track.alignment import AnnotatedWindow
from app.lib.product_track.config import TrackingConfig


@dataclass(frozen=True)
class ScoredWindow:
    """An :class:`AnnotatedWindow` augmented with the composite score
    + per-component breakdown. The picker sees only this — never the
    raw frame data."""

    window: AnnotatedWindow
    composite_score: float
    score_components: dict[str, float] = field(default_factory=dict)


class SubsetPicker(Protocol):
    """The picker is responsible for honoring the duration target +
    chronological ordering. Implementations:

      * gpt-4o-mini in the worker
      * deterministic greedy (this module's :func:`greedy_pick`)
        for tests + as a fallback if the LLM call fails
    """

    def pick(
        self,
        candidates: list[ScoredWindow],
        *,
        duration_preset_sec: int,
        config: TrackingConfig,
    ) -> list[ScoredWindow]: ...


def score_windows(
    windows: list[AnnotatedWindow],
    *,
    duration_preset_sec: int,
    config: TrackingConfig | None = None,
) -> list[ScoredWindow]:
    """Score accepted windows. Rejected windows are dropped — the
    picker never sees them.

    Composite weights (sum to 1.0 by construction in TrackingConfig):
      * prominence = avg_bbox_area_pct (already in [0, 1])
      * narration = 1 if has_narration_mention else 0
      * ocr = 1 if has_ocr_overlap else 0
      * duration_fitness = how close window duration is to the per-
        window target = preset / target_count. Triangular: 1.0 at
        target, linearly decreasing to 0 at 0× and 2× target.
      * spread_bonus = encourages picking windows from different
        timeline positions. Computed at score time as a flat 1.0
        and reweighted by the picker if it has timeline context;
        the scorer can't compute this in isolation since it depends
        on the chosen subset.
    """
    cfg = config or TrackingConfig()
    accepted = [w for w in windows if w.is_accepted]
    if not accepted:
        return []

    # Heuristic per-window target duration. We assume the final clip
    # has 3-5 windows (matches the auto-shorts cluster size locked
    # in the existing shorts_auto module). Use 4 as the midpoint.
    target_window_count = 4
    target_per_window_ms = (duration_preset_sec * 1000) // target_window_count

    out: list[ScoredWindow] = []
    for w in accepted:
        prominence = float(w.avg_bbox_area_pct)
        narration = 1.0 if w.has_narration_mention else 0.0
        ocr = 1.0 if w.has_ocr_overlap else 0.0
        duration_fitness = _triangular_fit(
            value=w.duration_ms, target=target_per_window_ms
        )
        spread_bonus = 1.0  # picker-reweighted; flat at score time

        composite = (
            cfg.score_weight_prominence * prominence
            + cfg.score_weight_narration * narration
            + cfg.score_weight_ocr * ocr
            + cfg.score_weight_duration_fitness * duration_fitness
            + cfg.score_weight_spread_bonus * spread_bonus
        )
        # Numerical safety: clamp to [0, 1] in case weights drift
        # past 1.0 in a future tuning. Contracts validator hard-gates
        # composite_score in [0, 1].
        composite = max(0.0, min(1.0, composite))

        out.append(
            ScoredWindow(
                window=w,
                composite_score=composite,
                score_components={
                    "prominence": prominence,
                    "narration": narration,
                    "ocr": ocr,
                    "duration_fitness": duration_fitness,
                    "spread_bonus": spread_bonus,
                },
            )
        )
    return out


def select_subset(
    scored: list[ScoredWindow],
    *,
    picker: SubsetPicker,
    duration_preset_sec: int,
    config: TrackingConfig | None = None,
) -> list[ScoredWindow]:
    """Hand scored candidates to the picker. The picker MUST honor
    the hard duration cap (preset × overshoot factor). This wrapper
    enforces:
      * chronological output order (by window_start_ms)
      * the duration overshoot guard (a slightly-paranoid trim if
        the picker overshoots — last resort, should never fire in
        prod since the picker prompt enforces it).
    """
    cfg = config or TrackingConfig()
    if not scored:
        return []

    picked = picker.pick(
        scored, duration_preset_sec=duration_preset_sec, config=cfg
    )
    picked = sorted(picked, key=lambda s: s.window.window_start_ms)

    max_ms = int(duration_preset_sec * 1000 * cfg.subset_duration_overshoot_factor)
    total_ms = sum(s.window.duration_ms for s in picked)
    while total_ms > max_ms and picked:
        # Drop the lowest-composite-score window first.
        worst = min(picked, key=lambda s: s.composite_score)
        picked.remove(worst)
        total_ms = sum(s.window.duration_ms for s in picked)

    return picked


# ---------- deterministic fallback picker ----------


@dataclass(frozen=True)
class GreedyPicker:
    """Deterministic greedy picker. Sorts by composite score desc,
    accumulates windows until the duration target is hit (without
    overshooting beyond the cfg overshoot factor).

    Used as the test fixture and as the worker's fallback if the LLM
    call fails / hits budget cap.
    """

    def pick(
        self,
        candidates: list[ScoredWindow],
        *,
        duration_preset_sec: int,
        config: TrackingConfig,
    ) -> list[ScoredWindow]:
        target_ms = duration_preset_sec * 1000
        max_ms = int(target_ms * config.subset_duration_overshoot_factor)
        ranked = sorted(candidates, key=lambda s: s.composite_score, reverse=True)
        chosen: list[ScoredWindow] = []
        running = 0
        for s in ranked:
            d = s.window.duration_ms
            if running + d > max_ms:
                continue
            chosen.append(s)
            running += d
            if running >= target_ms:
                break
        return chosen


# ---------- helpers ----------


def _triangular_fit(*, value: int, target: int) -> float:
    """Triangular fit: 1.0 at value=target, 0.0 at value=0 or
    value=2×target, linear in between. Clamped to [0, 1]."""
    if target <= 0:
        return 0.0
    if value <= 0 or value >= 2 * target:
        return 0.0
    if value <= target:
        return value / target
    return (2 * target - value) / target
