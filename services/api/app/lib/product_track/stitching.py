# VENDORED from heimdex-media-pipelines v0.12.3 (5d82c7d).
# See app/lib/product_track/__init__.py for the sync ritual.
"""Stitching plan — selected windows → CompositionSpec-shaped output.

Pure function: takes the picker's selected windows and assembles the
plan the worker hands to the api's ``/internal/products/{job_id}/complete``
callback.

Plan §6.2 step 8 v1 contract: hard cuts only, no transitions. The
worker is responsible for translating this plan into a real
``CompositionSpec`` and POSTing to ``/api/shorts/render``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.lib.product_track.config import TrackingConfig
from app.lib.product_track.subset_selector import (
    ScoredWindow,
)


@dataclass(frozen=True)
class StitchPlan:
    """Lib-level stitch plan. Worker enriches with catalog_entry_id +
    video_id (which the lib never sees) and constructs the contract
    payload."""

    duration_target_sec: int
    duration_actual_ms: int
    windows: list[ScoredWindow]
    scorer_version: str
    subset_picker_version: str


def build_stitch_plan(
    selected: list[ScoredWindow],
    *,
    duration_target_sec: int,
    config: TrackingConfig | None = None,
) -> StitchPlan:
    """Assemble the stitch plan. Windows are reordered chronologically
    here (paranoid — :func:`select_subset` already does this; we
    re-sort so a hand-crafted picker can't accidentally produce an
    out-of-order plan).

    Raises ``ValueError`` if ``selected`` is empty — the api contract
    requires ``windows: list[StitchWindow] = Field(..., min_length=1)``.
    The worker must catch this and route to ``/fail`` with a
    ``no_qualifying_windows`` reason rather than ``/complete``.
    """
    cfg = config or TrackingConfig()

    if not selected:
        raise ValueError(
            "build_stitch_plan requires at least one selected window — "
            "callers must route to /fail when select_subset returns []"
        )

    sorted_windows = sorted(
        selected, key=lambda s: s.window.window_start_ms
    )
    duration_actual_ms = sum(s.window.duration_ms for s in sorted_windows)

    return StitchPlan(
        duration_target_sec=duration_target_sec,
        duration_actual_ms=duration_actual_ms,
        windows=sorted_windows,
        scorer_version=cfg.tracker_version,
        subset_picker_version=cfg.subset_picker_version,
    )
