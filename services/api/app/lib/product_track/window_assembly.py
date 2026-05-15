# VENDORED from heimdex-media-pipelines v0.12.3 (5d82c7d).
# See app/lib/product_track/__init__.py for the sync ritual.
"""Window assembly — group SAM2-propagated frames into AppearanceWindows.

Pure function: takes :class:`FrameDetection` rows from
:mod:`sam2_pass`, returns :class:`AssembledWindow` records that the
worker turns into ``AppearanceWindow`` contracts on the API callback.

Algorithm (plan §6.2 step 4):

  1. Group detections by ``scene_id``.
  2. Within scene, sort by ``frame_timestamp_ms``.
  3. Merge consecutive samples whose gap < ``merge_gap_threshold_ms``
     into one window. The SAM2 sample cadence (5 fps = 200 ms) means
     a single dropped sample looks like a 400 ms gap; any user-visible
     "discontinuity" needs to be at least 2 s.
  4. Per window: compute averages + peak from the contained frames.
  5. Filter: drop windows shorter than ``min_window_duration_ms``,
     with ``avg_bbox_area_pct < min_avg_bbox_area_pct``, or with
     ``avg_confidence < min_avg_confidence``. Rejected windows are
     KEPT in the output list with a populated ``rejected_reason`` so
     the API can persist the rejected rows for threshold tuning later.
  6. Cap accepted windows at ``max_windows_per_product`` — sort by
     a quality proxy (avg_confidence × avg_bbox_area_pct) descending
     and drop the tail. Rejected windows are not capped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.lib.product_track.config import TrackingConfig


@dataclass(frozen=True)
class FrameDetection:
    """One SAM2-propagated frame sample for a single catalog entry.

    Constructed by :mod:`sam2_pass`. Frame ordering within a scene is
    by ``frame_timestamp_ms``, NOT ``frame_idx`` — frame indices are
    scene-relative and reset at scene boundaries, while timestamps
    are absolute over the source video.
    """

    scene_id: str
    frame_idx: int
    frame_timestamp_ms: int
    bbox_area_pct: float  # bbox area / frame area, in [0, 1]
    confidence: float  # SAM2 mask confidence in [0, 1]


# Rejection reasons — string literals matching the contracts'
# ``RejectedReason`` enum so the worker can pass them through without
# re-mapping.
REJECT_TOO_SHORT = "duration_below_floor"
REJECT_BBOX_TOO_SMALL = "bbox_area_below_floor"
REJECT_LOW_CONFIDENCE = "confidence_below_floor"


@dataclass(frozen=True)
class AssembledWindow:
    """One assembled appearance window. Worker maps this to
    ``heimdex_media_contracts.product.AppearanceWindow``."""

    scene_id: str
    window_start_ms: int
    window_end_ms: int
    avg_bbox_area_pct: float
    avg_confidence: float
    peak_confidence: float
    frame_count: int
    rejected_reason: str | None = None

    @property
    def duration_ms(self) -> int:
        return self.window_end_ms - self.window_start_ms

    @property
    def is_accepted(self) -> bool:
        return self.rejected_reason is None


def assemble_windows(
    detections: list[FrameDetection],
    *,
    config: TrackingConfig | None = None,
) -> list[AssembledWindow]:
    """Group per-frame detections into appearance windows.

    Returns the full list of windows — both accepted and rejected.
    Workers persist all of them for threshold-tuning visibility but
    only feed accepted ones to the subset selector.
    """
    cfg = config or TrackingConfig()

    if not detections:
        return []

    # Group by scene_id, preserving deterministic order across scenes.
    by_scene: dict[str, list[FrameDetection]] = {}
    for d in detections:
        by_scene.setdefault(d.scene_id, []).append(d)

    assembled: list[AssembledWindow] = []
    for scene_id in sorted(by_scene.keys()):
        frames = sorted(by_scene[scene_id], key=lambda f: f.frame_timestamp_ms)
        assembled.extend(_assemble_one_scene(scene_id, frames, cfg))

    accepted = [w for w in assembled if w.is_accepted]
    rejected = [w for w in assembled if not w.is_accepted]

    # Cap accepted windows globally (across scenes). Quality proxy
    # = avg_confidence × avg_bbox_area_pct so we prefer windows
    # where the product is both prominent AND tracked confidently.
    if len(accepted) > cfg.max_windows_per_product:
        accepted.sort(
            key=lambda w: w.avg_confidence * w.avg_bbox_area_pct,
            reverse=True,
        )
        accepted = accepted[: cfg.max_windows_per_product]

    # Stable order by start time for the final output (across scenes).
    out = accepted + rejected
    out.sort(key=lambda w: (w.scene_id, w.window_start_ms))
    return out


def _assemble_one_scene(
    scene_id: str,
    frames: list[FrameDetection],
    cfg: TrackingConfig,
) -> list[AssembledWindow]:
    """Walk a scene's frames in time order, splitting on gaps that
    exceed the merge threshold. Apply the per-window filter at the
    end."""

    if not frames:
        return []

    runs: list[list[FrameDetection]] = [[frames[0]]]
    for f in frames[1:]:
        prev = runs[-1][-1]
        gap = f.frame_timestamp_ms - prev.frame_timestamp_ms
        if gap > cfg.merge_gap_threshold_ms:
            runs.append([f])
        else:
            runs[-1].append(f)

    out: list[AssembledWindow] = []
    for run in runs:
        out.append(_window_from_run(scene_id, run, cfg))
    return out


def _window_from_run(
    scene_id: str,
    run: list[FrameDetection],
    cfg: TrackingConfig,
) -> AssembledWindow:
    start = run[0].frame_timestamp_ms
    end = run[-1].frame_timestamp_ms
    n = len(run)
    avg_bbox = sum(f.bbox_area_pct for f in run) / n
    avg_conf = sum(f.confidence for f in run) / n
    peak_conf = max(f.confidence for f in run)

    # Single-frame runs synthesize a 1-sample-period duration so
    # window_end_ms > window_start_ms (contract validator requirement).
    # 200 ms matches the 5 fps default sampling cadence.
    if end <= start:
        end = start + max(1, 1000 // cfg.sam2_sample_fps)

    duration = end - start
    rejected: str | None = None
    if duration < cfg.min_window_duration_ms:
        rejected = REJECT_TOO_SHORT
    elif avg_bbox < cfg.min_avg_bbox_area_pct:
        rejected = REJECT_BBOX_TOO_SMALL
    elif avg_conf < cfg.min_avg_confidence:
        rejected = REJECT_LOW_CONFIDENCE

    return AssembledWindow(
        scene_id=scene_id,
        window_start_ms=start,
        window_end_ms=end,
        avg_bbox_area_pct=avg_bbox,
        avg_confidence=avg_conf,
        peak_confidence=peak_conf,
        frame_count=n,
        rejected_reason=rejected,
    )
