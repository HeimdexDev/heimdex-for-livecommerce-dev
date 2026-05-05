"""Segment assembly — port of standalone product-auto-shorts'
``segmentation.py::group_product_segments``.

Takes ``MentionedScene[]`` (from ``mention_extractor``) and folds
runs of consecutive scenes within ``MAX_GAP_MS`` of each other into
``MentionSegment[]``. Drops segments shorter than ``MIN_SEGMENT_MS``
because clips below that floor produce poor clip pacing.

Pure function — no I/O, no async, no external deps. Trivially
testable.

Constants are kept in milliseconds (the rest of this codebase uses
ms uniformly) but mirror the standalone repo's seconds:

    standalone MAX_GAP_SECONDS = 5.0  → MAX_GAP_MS = 5_000
    standalone MIN_SEGMENT_SECONDS = 20.0 → MIN_SEGMENT_MS = 20_000
"""

from __future__ import annotations

import logging

from app.modules.shorts_auto_product.track_stt.models import (
    MentionedScene,
    MentionSegment,
)

logger = logging.getLogger(__name__)


# Maximum allowed gap between consecutive mentioned scenes within
# the same segment. Picked to absorb a single non-product scene
# (typical Korean livecommerce scenes are 1-15s) without breaking
# the segment, while preventing two distant clusters of mentions
# from collapsing into one too-long segment.
MAX_GAP_MS = 5_000

# Minimum total segment duration. Below this floor the clip would
# be too short to carry a hook + selling moment. Standalone repo
# uses 20s; we keep that.
MIN_SEGMENT_MS = 20_000


def group_into_segments(
    scenes: list[MentionedScene],
) -> list[MentionSegment]:
    """Group consecutive mentioned scenes into segments.

    Args:
        scenes: Mentioned scenes in any order. Sorted internally by
            ``start_ms`` ascending so callers don't have to.

    Returns:
        ``MentionSegment[]`` ordered chronologically by ``start_ms``.
        Empty when input is empty or when no run of scenes meets the
        ``MIN_SEGMENT_MS`` floor.
    """

    if not scenes:
        return []

    chronological = sorted(scenes, key=lambda s: s.start_ms)

    segments: list[MentionSegment] = []
    current_scenes: list[MentionedScene] = [chronological[0]]
    current_start = chronological[0].start_ms
    current_end = chronological[0].end_ms

    for scene in chronological[1:]:
        gap = scene.start_ms - current_end
        if gap <= MAX_GAP_MS:
            # Extend current segment.
            current_scenes.append(scene)
            current_end = max(current_end, scene.end_ms)
        else:
            # Close current, open a new one.
            _emit_if_long_enough(
                segments, current_scenes, current_start, current_end,
            )
            current_scenes = [scene]
            current_start = scene.start_ms
            current_end = scene.end_ms

    _emit_if_long_enough(
        segments, current_scenes, current_start, current_end,
    )

    logger.info(
        "stt_segment_assembly_completed",
        extra={
            "input_scene_count": len(scenes),
            "output_segment_count": len(segments),
            "kept_scene_count": sum(len(s.scenes) for s in segments),
            "max_gap_ms": MAX_GAP_MS,
            "min_segment_ms": MIN_SEGMENT_MS,
        },
    )
    return segments


def _emit_if_long_enough(
    segments: list[MentionSegment],
    scenes: list[MentionedScene],
    start_ms: int,
    end_ms: int,
) -> None:
    if (end_ms - start_ms) >= MIN_SEGMENT_MS:
        segments.append(
            MentionSegment(
                start_ms=start_ms,
                end_ms=end_ms,
                scenes=list(scenes),
            )
        )
