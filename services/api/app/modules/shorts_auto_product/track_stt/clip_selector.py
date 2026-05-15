"""Clip selection — port of standalone product-auto-shorts'
``main.py::_select_clip_groups``.

Takes ``ScoredChunk[]`` (across all segments) and picks the
contiguous, chronologically-ordered subset whose total duration is
closest to ``target_duration_ms`` while maximizing composite score.

Pure function — no LLM, no I/O. Deterministic.

Strategy:

1. Sort by ``composite`` score descending → find the best seed.
2. From that seed forward in time, accumulate adjacent chunks until
   the target duration is filled.
3. If accumulation falls short, expand backward from the seed.
4. Cap at ``MAX_TARGET_OVERSHOOT_MS`` so a sparse segment can't
   produce a clip 2× the requested duration.

Selection is single-clip in v1 — the wizard requests
``length_seconds`` ∈ {30, 60, 90} and the user gets one short. The
standalone repo's ``clip_count`` parameter is intentionally NOT
ported because the existing wizard already handles
``requested_count`` at the parent/child level (multiple shorts =
multiple parent rows, each running this pipeline once).
"""

from __future__ import annotations

import logging

from app.modules.shorts_auto_product.track_stt.models import ScoredChunk

logger = logging.getLogger(__name__)


# Allowable overshoot above target. Korean livecommerce chunks are
# typically 20s; the realistic options are landing exactly on target
# or +1 chunk (≈+20s). Anything more dilutes the clip.
MAX_TARGET_OVERSHOOT_MS = 20_000

# Minimum acceptable clip duration relative to target. Below this
# floor the clip is too short to feel intentional — better to fail
# the pipeline and let the user pick a different product than ship a
# 12s "60-second" clip.
_MIN_DURATION_FRACTION = 0.5


def select_top_chunks(
    *,
    chunks: list[ScoredChunk],
    target_duration_ms: int,
) -> list[ScoredChunk]:
    """Pick the chunks that go into the final clip.

    Args:
        chunks: All scored chunks across all segments. Order doesn't
            matter — sorted internally.
        target_duration_ms: e.g., 30_000 / 60_000 / 90_000 from the
            wizard's ``length_seconds`` × 1000.

    Returns:
        Chronologically-ordered chunks. Returns empty when no
        contiguous run reaches ``_MIN_DURATION_FRACTION * target``;
        caller surfaces that as the friendly Korean
        ``no_mentions_found`` message.
    """
    if not chunks or target_duration_ms <= 0:
        return []

    # Sort once for deterministic seed ordering.
    chronological = sorted(chunks, key=lambda c: c.start_ms)
    by_score = sorted(chronological, key=lambda c: -c.composite)

    cap_ms = target_duration_ms + MAX_TARGET_OVERSHOOT_MS

    # Try each seed in score order. First seed that produces a
    # window passing the floor wins. This biases the clip toward
    # the highest-importance chunk while still respecting
    # chronological ordering for the assembled output.
    for seed in by_score:
        try:
            seed_idx = chronological.index(seed)
        except ValueError:  # pragma: no cover - chronological is a sort of chunks
            continue

        forward = _accumulate_forward(
            chronological=chronological,
            seed_idx=seed_idx,
            target_ms=target_duration_ms,
            cap_ms=cap_ms,
        )
        backward_extended = _expand_backward(
            chronological=chronological,
            window=forward,
            seed_idx=seed_idx,
            target_ms=target_duration_ms,
            cap_ms=cap_ms,
        )

        duration = _window_duration_ms(backward_extended)
        floor = int(target_duration_ms * _MIN_DURATION_FRACTION)
        if duration >= floor:
            logger.info(
                "stt_clip_selection_completed",
                extra={
                    "seed_start_ms": seed.start_ms,
                    "seed_composite": seed.composite,
                    "selected_chunk_count": len(backward_extended),
                    "duration_ms": duration,
                    "target_ms": target_duration_ms,
                },
            )
            return backward_extended

    # No seed produced a long-enough window. Caller treats this as
    # "no clip possible" — usually means BM25 found <2 segments
    # totaling <30s, which is too sparse to render.
    logger.info(
        "stt_clip_selection_no_window_meets_floor",
        extra={
            "chunk_count": len(chunks),
            "target_ms": target_duration_ms,
        },
    )
    return []


# ---------- internals ----------


def _accumulate_forward(
    *,
    chronological: list[ScoredChunk],
    seed_idx: int,
    target_ms: int,
    cap_ms: int,
) -> list[ScoredChunk]:
    """Walk forward from seed_idx until total duration ≥ target_ms,
    bounded by cap_ms. Stops short if the next chunk would push
    past the cap.
    """
    window = [chronological[seed_idx]]
    duration = chronological[seed_idx].end_ms - chronological[seed_idx].start_ms
    for i in range(seed_idx + 1, len(chronological)):
        next_chunk = chronological[i]
        next_dur = next_chunk.end_ms - next_chunk.start_ms
        projected = duration + next_dur
        if projected > cap_ms:
            break
        window.append(next_chunk)
        duration = projected
        if duration >= target_ms:
            break
    return window


def _expand_backward(
    *,
    chronological: list[ScoredChunk],
    window: list[ScoredChunk],
    seed_idx: int,
    target_ms: int,
    cap_ms: int,
) -> list[ScoredChunk]:
    """If the forward window is short of target, extend backward."""
    duration = _window_duration_ms(window)
    if duration >= target_ms:
        return window

    extended = list(window)
    for i in range(seed_idx - 1, -1, -1):
        prev_chunk = chronological[i]
        prev_dur = prev_chunk.end_ms - prev_chunk.start_ms
        projected = duration + prev_dur
        if projected > cap_ms:
            break
        extended.insert(0, prev_chunk)
        duration = projected
        if duration >= target_ms:
            break
    return extended


def _window_duration_ms(window: list[ScoredChunk]) -> int:
    return sum(c.end_ms - c.start_ms for c in window)
