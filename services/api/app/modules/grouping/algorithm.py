"""
Pure functions for semantic scene grouping.

Groups consecutive video scenes by computing pairwise similarity between
adjacent scenes using text and visual embedding vectors. Boundaries are
placed where similarity drops below a configurable threshold.

This module has ZERO side effects — no I/O, no OpenSearch, no HTTP, no
logging. It operates exclusively on plain Python data structures, making
it trivially unit-testable.

Embedding assumptions (from app/modules/search/embedding.py):
- Text embeddings: 1024-dim, L2-normalized (intfloat/multilingual-e5-large)
- Visual embeddings: 768-dim, L2-normalized (google/siglip2-base-patch16-256)
- For L2-normalized vectors: cosine_similarity(a, b) == dot_product(a, b)
"""

from __future__ import annotations

import math
from typing import Sequence, cast


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
) -> list[float]:
    """Compute similarity between each consecutive pair of scenes.

    For N scenes, returns N-1 similarity scores in [0.0, 1.0].

    Signal fusion (adaptive weighting):
    - If both text + visual embeddings present: weighted average
    - If only one signal present: uses it alone (weight 1.0)
    - If neither present: returns 0.5 (neutral — no boundary created)

    Args:
        scenes: Scene dicts sorted by start_ms. Each must contain at least
            ``start_ms``. Optionally ``embedding_vector`` (list[float])
            and ``visual_embedding`` (list[float]).
        text_weight: Relative weight for text embedding similarity.
        visual_weight: Relative weight for visual embedding similarity.

    Returns:
        List of N-1 float similarity scores. scores[i] is the similarity
        between scenes[i] and scenes[i+1].
    """
    if len(scenes) < 2:
        return []

    similarities: list[float] = []

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
            sim = (
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
            sim = 0.5  # Neutral — avoid creating false boundaries

        # Clamp to [0, 1] for safety (floating-point edge cases)
        similarities.append(max(0.0, min(1.0, sim)))

    return similarities


def find_group_boundaries(
    similarities: list[float],
    total_scenes: int,
    *,
    threshold: float = 0.55,
    min_group_size: int = 2,
) -> list[tuple[int, int]]:
    """Find group boundaries from pairwise similarity scores.

    Args:
        similarities: N-1 similarity scores from compute_pairwise_similarity.
        total_scenes: Total number of scenes (len(similarities) + 1).
        threshold: Similarity below this triggers a boundary.
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

    # Step 1: Find initial boundaries at similarity drops
    boundary_indices: list[int] = [0]  # First group always starts at 0
    for i, sim in enumerate(similarities):
        if sim < threshold:
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
    similarities: list[float],
    min_group_size: int,
) -> list[tuple[int, int]]:
    """Merge groups smaller than min_group_size into neighbors.

    Strategy: merge into the adjacent group connected by the higher
    similarity score. Process from smallest groups first.
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

            # Find which neighbor to merge with
            left_sim = (
                similarities[start - 1] if start > 0 and i > 0 else -1.0
            )
            right_sim = (
                similarities[end]
                if end < len(similarities) and i + 1 < len(merged)
                else -1.0
            )

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
