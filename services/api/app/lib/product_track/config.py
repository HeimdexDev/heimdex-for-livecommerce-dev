# VENDORED from heimdex-media-pipelines v0.12.3 (5d82c7d).
# See app/lib/product_track/__init__.py for the sync ritual.
"""Tracking pipeline configuration — thresholds + dataclass.

Defaults mirror plan §6.2 of `shorts-auto-product-v2.md`. Thresholds
are calibrated by Phase 2 spike on staging goldens; the values here
are the prod starting point. Workers can override via
:class:`TrackingConfig` at construction time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Pipeline + scorer version strings. Bump together when any threshold
# or algorithm here changes meaningfully — the API persists these on
# every appearance + stitching plan, so historical jobs remain
# attributable to the version that produced them.
TRACKER_VERSION = "v1.0"
SUBSET_PICKER_VERSION = "v1.0"

# SigLIP2 retrieval thresholds (plan §6.2 step 2).
COARSE_PREFILTER_THRESHOLD = 0.45
PRECISE_PASS_THRESHOLD = 0.72
COARSE_TOP_K = 60  # top scenes from the OS coarse pre-filter

# SAM2 sampling cadence (plan §6.2 step 3). Sampling at 5 fps =
# 200 ms between samples. Bbox is interpolated linearly between samples
# so the published windows aren't artificially gappy.
SAM2_SAMPLE_FPS = 5

# Window assembly thresholds (plan §6.2 step 4).
MIN_WINDOW_DURATION_MS = 1500
MIN_AVG_BBOX_AREA_PCT = 0.02
MIN_AVG_CONFIDENCE = 0.7
MERGE_GAP_THRESHOLD_MS = 2000
MAX_WINDOWS_PER_PRODUCT = 30

# Subset selection composite score weights (plan §6.2 step 7). Sum
# to 1.0 by construction; not enforced at runtime but worth keeping
# them so when a tuning pass shifts one weight, the others land
# proportionally.
SCORE_WEIGHT_PROMINENCE = 0.35
SCORE_WEIGHT_NARRATION = 0.25
SCORE_WEIGHT_OCR = 0.15
SCORE_WEIGHT_DURATION_FITNESS = 0.15
SCORE_WEIGHT_SPREAD_BONUS = 0.10

# Subset selection hard caps.
SUBSET_DURATION_OVERSHOOT_FACTOR = 1.05  # never overshoot preset by >5%


@dataclass(frozen=True)
class TrackingConfig:
    """Per-job tuning knobs. Defaults mirror the constants above."""

    # Retrieval.
    coarse_prefilter_threshold: float = COARSE_PREFILTER_THRESHOLD
    precise_pass_threshold: float = PRECISE_PASS_THRESHOLD
    coarse_top_k: int = COARSE_TOP_K

    # SAM2 propagation.
    sam2_sample_fps: int = SAM2_SAMPLE_FPS

    # Window assembly.
    min_window_duration_ms: int = MIN_WINDOW_DURATION_MS
    min_avg_bbox_area_pct: float = MIN_AVG_BBOX_AREA_PCT
    min_avg_confidence: float = MIN_AVG_CONFIDENCE
    merge_gap_threshold_ms: int = MERGE_GAP_THRESHOLD_MS
    max_windows_per_product: int = MAX_WINDOWS_PER_PRODUCT

    # Subset scoring weights.
    score_weight_prominence: float = SCORE_WEIGHT_PROMINENCE
    score_weight_narration: float = SCORE_WEIGHT_NARRATION
    score_weight_ocr: float = SCORE_WEIGHT_OCR
    score_weight_duration_fitness: float = SCORE_WEIGHT_DURATION_FITNESS
    score_weight_spread_bonus: float = SCORE_WEIGHT_SPREAD_BONUS

    # Subset assembly hard cap.
    subset_duration_overshoot_factor: float = SUBSET_DURATION_OVERSHOOT_FACTOR

    # Version strings. Workers don't override these in the common
    # case; tests sometimes do.
    tracker_version: str = TRACKER_VERSION
    subset_picker_version: str = SUBSET_PICKER_VERSION
