"""
Pure functions for semantic scene grouping.

Groups consecutive video scenes by computing pairwise similarity between
adjacent scenes using text and visual embedding vectors. Boundaries are
placed where similarity drops significantly below the local average,
using an adaptive threshold computed from each video's own similarity
distribution.

This module has ZERO side effects — no I/O, no OpenSearch, no HTTP, no
logging. It operates exclusively on plain Python data structures, making
it trivially unit-testable.

Embedding assumptions (from app/modules/search/embedding.py):
- Text embeddings: 1024-dim, L2-normalized (intfloat/multilingual-e5-large)
- Visual embeddings: 768-dim, L2-normalized (google/siglip2-base-patch16-256)
- For L2-normalized vectors: cosine_similarity(a, b) == dot_product(a, b)

Adaptive threshold design:
- Pairs where both scenes lack embeddings get a sentinel value (None)
  instead of a neutral score, so they don't pollute the similarity
  distribution or create false boundaries.
- The threshold is computed from REAL similarity values only:
  adaptive_threshold = mean(real_sims) - sensitivity * stdev(real_sims)
- This places boundaries at natural dips relative to each video's own
  similarity baseline, working correctly for both short videos with
  tight similarity distributions and long videos with sparse embeddings.
"""

from __future__ import annotations

import math
from typing import Sequence, cast

# Sentinel value for pairs where neither scene has embeddings.
# These pairs are skipped during boundary detection (no information
# to determine similarity, so no boundary should be placed).
SIMILARITY_UNKNOWN: None = None


def _dot_product(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product of two vectors.

    For L2-normalized vectors this equals cosine similarity.
    Returns 0.0 if vectors are empty or mismatched in length.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    return math.fsum(x * y for x, y in zip(a, b))


def compute_pairwise_similarity(
    scenes: list[dict[str, object]],
    *,
    text_weight: float = 0.6,
    visual_weight: float = 0.4,
) -> list[float | None]:
    """Compute similarity between each consecutive pair of scenes.

    For N scenes, returns N-1 similarity scores.

    Signal fusion (adaptive weighting):
    - If both text + visual embeddings present: weighted average
    - If only one signal present: uses it alone (weight 1.0)
    - If neither present: returns None (unknown — no boundary created)

    Args:
        scenes: Scene dicts sorted by start_ms. Each must contain at least
            ``start_ms``. Optionally ``embedding_vector`` (list[float])
            and ``visual_embedding`` (list[float]).
        text_weight: Relative weight for text embedding similarity.
        visual_weight: Relative weight for visual embedding similarity.

    Returns:
        List of N-1 values. Each is either a float in [0.0, 1.0] or None
        (unknown similarity due to missing embeddings). scores[i] is the
        similarity between scenes[i] and scenes[i+1].
    """
    if len(scenes) < 2:
        return []

    similarities: list[float | None] = []

    for i in range(len(scenes) - 1):
        a = scenes[i]
        b = scenes[i + 1]

        text_a = a.get("embedding_vector")
        text_b = b.get("embedding_vector")
        vis_a = a.get("visual_embedding")
        vis_b = b.get("visual_embedding")

        has_text = bool(text_a and text_b)
        has_visual = bool(vis_a and vis_b)

        if has_text and has_visual:
            total = text_weight + visual_weight
            ta = cast(Sequence[float], text_a)
            tb = cast(Sequence[float], text_b)
            va = cast(Sequence[float], vis_a)
            vb = cast(Sequence[float], vis_b)
            sim: float = (
                text_weight * _dot_product(ta, tb)
                + visual_weight * _dot_product(va, vb)
            ) / total
        elif has_text:
            sim = _dot_product(
                cast(Sequence[float], text_a),
                cast(Sequence[float], text_b),
            )
        elif has_visual:
            sim = _dot_product(
                cast(Sequence[float], vis_a),
                cast(Sequence[float], vis_b),
            )
        else:
            similarities.append(SIMILARITY_UNKNOWN)
            continue

        # Clamp to [0, 1] for safety (floating-point edge cases)
        similarities.append(max(0.0, min(1.0, sim)))

    return similarities


def _compute_adaptive_threshold(
    similarities: list[float | None],
    *,
    sensitivity: float = 1.0,
    fallback_threshold: float = 0.55,
) -> float:
    """Compute adaptive threshold from real (non-None) similarity values.

    threshold = mean(real_sims) - sensitivity * stdev(real_sims)

    This places boundaries at natural dips relative to each video's own
    similarity distribution. For videos where adjacent scenes are very
    similar (mean ~0.8, stdev ~0.04), the threshold might be ~0.76,
    catching only real topic changes. For diverse videos (mean ~0.5,
    stdev ~0.15), the threshold would be ~0.35, allowing more variation.

    Args:
        similarities: Pairwise similarities with possible None values.
        sensitivity: Number of standard deviations below the mean.
            Higher = fewer groups (more permissive).
            Lower = more groups (more sensitive to dips).
        fallback_threshold: Used when there are fewer than 2 real
            similarity values (can't compute meaningful statistics).

    Returns:
        The adaptive threshold value.
    """
    real_sims = [s for s in similarities if s is not None]

    if len(real_sims) < 2:
        return fallback_threshold

    mean = sum(real_sims) / len(real_sims)
    variance = sum((s - mean) ** 2 for s in real_sims) / len(real_sims)
    stdev = math.sqrt(variance)

    return mean - sensitivity * stdev


def find_group_boundaries(
    similarities: list[float | None],
    total_scenes: int,
    *,
    threshold: float | None = None,
    sensitivity: float = 1.0,
    fallback_threshold: float = 0.55,
    min_group_size: int = 2,
) -> list[tuple[int, int]]:
    """Find group boundaries from pairwise similarity scores.

    Uses adaptive thresholding: the threshold is computed from the
    distribution of REAL similarity values (ignoring None/unknown pairs).
    An explicit threshold can be provided to override adaptive behavior.

    Args:
        similarities: N-1 similarity scores from compute_pairwise_similarity.
            May contain None values for unknown pairs.
        total_scenes: Total number of scenes (len(similarities) + 1).
        threshold: If provided, overrides adaptive threshold computation.
        sensitivity: Std devs below mean for adaptive threshold (default 1.0).
        fallback_threshold: Used when adaptive can't be computed (< 2 real
            values) and no explicit threshold is provided.
        min_group_size: Groups smaller than this are merged into the
            adjacent group with the higher connecting similarity.

    Returns:
        List of (start_index, end_index) tuples (inclusive on both ends).
        Covers all scenes: boundaries[0][0] == 0 and
        boundaries[-1][1] == total_scenes - 1.
    """
    if total_scenes == 0:
        return []
    if total_scenes == 1:
        return [(0, 0)]
    if not similarities:
        return [(0, total_scenes - 1)]

    # Compute threshold: explicit > adaptive > fallback
    effective_threshold = (
        threshold
        if threshold is not None
        else _compute_adaptive_threshold(
            similarities,
            sensitivity=sensitivity,
            fallback_threshold=fallback_threshold,
        )
    )

    # Step 1: Find initial boundaries at similarity drops.
    # None values (unknown similarity) are SKIPPED — they don't create
    # boundaries because we have no information about topic change.
    boundary_indices: list[int] = [0]  # First group always starts at 0
    for i, sim in enumerate(similarities):
        if sim is not None and sim < effective_threshold:
            boundary_indices.append(i + 1)

    # Step 2: Build initial groups
    groups: list[tuple[int, int]] = []
    for idx, start in enumerate(boundary_indices):
        end = (
            boundary_indices[idx + 1] - 1
            if idx + 1 < len(boundary_indices)
            else total_scenes - 1
        )
        groups.append((start, end))

    # Step 3: Merge undersized groups into adjacent groups
    if min_group_size > 1 and len(groups) > 1:
        groups = _merge_small_groups(groups, similarities, min_group_size)

    return groups


def _merge_small_groups(
    groups: list[tuple[int, int]],
    similarities: list[float | None],
    min_group_size: int,
) -> list[tuple[int, int]]:
    """Merge groups smaller than min_group_size into neighbors.

    Strategy: merge into the adjacent group connected by the higher
    similarity score. Unknown (None) similarities are treated as -1.0
    for comparison (least preferred merge direction).
    """
    merged = list(groups)
    changed = True

    while changed:
        changed = False
        new_merged: list[tuple[int, int]] = []
        skip_next = False

        for i, (start, end) in enumerate(merged):
            if skip_next:
                skip_next = False
                continue

            size = end - start + 1
            if size >= min_group_size or len(merged) <= 1:
                new_merged.append((start, end))
                continue

            # Find which neighbor to merge with.
            # Treat None as -1.0 for comparison purposes.
            left_raw = (
                similarities[start - 1] if start > 0 and i > 0 else None
            )
            right_raw = (
                similarities[end]
                if end < len(similarities) and i + 1 < len(merged)
                else None
            )
            left_sim = left_raw if left_raw is not None else -1.0
            right_sim = right_raw if right_raw is not None else -1.0

            if left_sim >= right_sim and left_sim >= 0 and new_merged:
                # Merge into left neighbor
                prev_start, _ = new_merged[-1]
                new_merged[-1] = (prev_start, end)
                changed = True
            elif right_sim >= 0 and i + 1 < len(merged):
                # Merge into right neighbor
                next_start, next_end = merged[i + 1]
                new_merged.append((start, next_end))
                skip_next = True
                changed = True
            else:
                # No valid neighbor — keep as-is
                new_merged.append((start, end))

        merged = new_merged

    return merged
