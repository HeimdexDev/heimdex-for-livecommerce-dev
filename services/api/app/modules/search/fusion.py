from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.search.normalize import get_normalized_char_count

logger = get_logger(__name__)

# Quality signal thresholds
MIN_TRANSCRIPT_CHARS = 20   # Very short transcripts get penalized
GOOD_TRANSCRIPT_CHARS = 100  # Full quality above this threshold
QUALITY_FLOOR = 0.85         # Minimum quality multiplier (raised from 0.7 to reduce
                             # penalty on scenes with strong captions but short transcripts)


@dataclass
class RankedItem:
    doc_id: str
    video_id: str
    source: dict[str, Any]
    lexical_rank: int | None = None
    lexical_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    visual_rank: int | None = None
    visual_score: float | None = None
    lexical_contribution: float = 0.0
    vector_contribution: float = 0.0
    visual_contribution: float = 0.0
    quality_factor: float = 1.0
    fused_score: float = 0.0
    adjusted_score: float = 0.0
    diversification_penalty: bool = False

def rrf_score(rank: int | None, k: int = 60) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (k + rank)


def compute_quality_factor(source: dict[str, Any]) -> float:
    """
    Compute quality factor based on combined text content character count.
    
    Considers transcript, OCR, AND scene_caption text. This ensures scenes
    with strong AI captions but short transcripts are not unfairly penalized
    in semantic search mode.
    
    Fallback chain for transcript:
    1. transcript_char_count_normalized (pre-computed normalized)
    2. transcript_char_count (legacy, raw count)
    3. Compute from transcript text using get_normalized_char_count()
    
    Returns:
        Quality factor between QUALITY_FLOOR (0.85) and 1.0
    """
    raw_char_count = source.get("transcript_char_count_normalized", 0)
    char_count = raw_char_count if isinstance(raw_char_count, int) else 0

    if char_count == 0:
        fallback_char_count = source.get("transcript_char_count", 0)
        char_count = fallback_char_count if isinstance(fallback_char_count, int) else 0

    if char_count == 0:
        transcript_raw = source.get("transcript_raw", "")
        transcript_norm = source.get("transcript_norm", "")
        transcript = transcript_raw if isinstance(transcript_raw, str) else ""
        if not transcript:
            transcript = transcript_norm if isinstance(transcript_norm, str) else ""
        if transcript:
            char_count = get_normalized_char_count(transcript)

    raw_ocr_char_count = source.get("ocr_char_count", 0)
    ocr_char_count = raw_ocr_char_count if isinstance(raw_ocr_char_count, int) else 0
    if ocr_char_count == 0:
        ocr_text_raw = source.get("ocr_text_raw", "")
        ocr_text_norm = source.get("ocr_text_norm", "")
        ocr_text = ocr_text_raw if isinstance(ocr_text_raw, str) else ""
        if not ocr_text:
            ocr_text = ocr_text_norm if isinstance(ocr_text_norm, str) else ""
        if ocr_text:
            ocr_char_count = get_normalized_char_count(ocr_text)

    # Include scene_caption in quality signal so that scenes with strong
    # AI captions (but minimal speech/OCR) are not penalized.
    caption_text = source.get("scene_caption", "")
    caption_char_count = 0
    if isinstance(caption_text, str) and caption_text:
        caption_char_count = get_normalized_char_count(caption_text)

    char_count = char_count + ocr_char_count + caption_char_count
    
    if char_count >= GOOD_TRANSCRIPT_CHARS:
        return 1.0
    elif char_count <= MIN_TRANSCRIPT_CHARS:
        return QUALITY_FLOOR
    else:
        ratio = (char_count - MIN_TRANSCRIPT_CHARS) / (GOOD_TRANSCRIPT_CHARS - MIN_TRANSCRIPT_CHARS)
        return QUALITY_FLOOR + ratio * (1.0 - QUALITY_FLOOR)


def compute_weighted_rrf(
    lexical_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    visual_results: list[dict[str, Any]],
    *,
    bm25_weight: float,
    text_knn_weight: float,
    visual_weight: float,
) -> list[RankedItem]:
    """Compute 3-way weighted Reciprocal Rank Fusion.

    Merges up to three ranked result lists (BM25, text kNN, visual kNN)
    using the RRF formula: score = weight * 1/(k + rank).  Documents absent
    from a list contribute 0 for that signal — they are not penalized, just
    not boosted.

    The three weights should sum to 1.0.  When a signal is disabled (e.g.
    visual search off), its weight should be 0.0 and its results list empty.

    After RRF scoring, a quality factor (0.85–1.0) based on content length
    (transcript + OCR + caption) is multiplied in to demote very-short scenes.

    Args:
        lexical_results: BM25 hits from OpenSearch.
        vector_results: Text kNN hits (E5 embedding).
        visual_results: Visual kNN hits (SigLIP2 embedding).
        bm25_weight: Weight for BM25 signal (0.0–1.0).
        text_knn_weight: Weight for text kNN signal (0.0–1.0).
        visual_weight: Weight for visual kNN signal (0.0–1.0).

    Returns:
        Ranked list of RankedItem sorted by adjusted_score descending.
    """
    settings = get_settings()
    k = settings.search_rrf_k

    items: dict[str, RankedItem] = {}

    # --- Pass 1: BM25 (lexical) results ---
    for rank, hit in enumerate(lexical_results, start=1):
        doc_id = str(hit.get("_id", ""))
        source_raw = hit.get("_source", {})
        source = source_raw if isinstance(source_raw, dict) else {}
        video_id = str(source.get("video_id", ""))

        if doc_id not in items:
            items[doc_id] = RankedItem(
                doc_id=doc_id,
                video_id=video_id,
                source=source,
            )

        items[doc_id].lexical_rank = rank
        lexical_score = hit.get("_score", 0.0)
        items[doc_id].lexical_score = (
            float(lexical_score) if isinstance(lexical_score, (int, float)) else 0.0
        )

    # --- Pass 2: Text kNN (vector) results ---
    for rank, hit in enumerate(vector_results, start=1):
        doc_id = str(hit.get("_id", ""))
        source_raw = hit.get("_source", {})
        source = source_raw if isinstance(source_raw, dict) else {}
        video_id = str(source.get("video_id", ""))

        if doc_id not in items:
            items[doc_id] = RankedItem(
                doc_id=doc_id,
                video_id=video_id,
                source=source,
            )

        items[doc_id].vector_rank = rank
        vector_score = hit.get("_score", 0.0)
        items[doc_id].vector_score = (
            float(vector_score) if isinstance(vector_score, (int, float)) else 0.0
        )

    # --- Pass 3: Visual kNN results ---
    for rank, hit in enumerate(visual_results, start=1):
        doc_id = str(hit.get("_id", ""))
        source_raw = hit.get("_source", {})
        source = source_raw if isinstance(source_raw, dict) else {}
        video_id = str(source.get("video_id", ""))

        if doc_id not in items:
            items[doc_id] = RankedItem(
                doc_id=doc_id,
                video_id=video_id,
                source=source,
            )

        items[doc_id].visual_rank = rank
        vis_score = hit.get("_score", 0.0)
        items[doc_id].visual_score = (
            float(vis_score) if isinstance(vis_score, (int, float)) else 0.0
        )

    # --- Compute weighted RRF scores ---
    for item in items.values():
        lex_contribution = bm25_weight * rrf_score(item.lexical_rank, k)
        vec_contribution = text_knn_weight * rrf_score(item.vector_rank, k)
        vis_contribution = visual_weight * rrf_score(item.visual_rank, k)
        item.lexical_contribution = lex_contribution
        item.vector_contribution = vec_contribution
        item.visual_contribution = vis_contribution
        item.fused_score = lex_contribution + vec_contribution + vis_contribution

        item.quality_factor = compute_quality_factor(item.source)
        item.adjusted_score = item.fused_score * item.quality_factor

    ranked = sorted(items.values(), key=lambda x: x.adjusted_score, reverse=True)

    logger.debug(
        "rrf_fusion_computed",
        total_candidates=len(ranked),
        lexical_count=len(lexical_results),
        vector_count=len(vector_results),
        visual_count=len(visual_results),
        bm25_weight=bm25_weight,
        text_knn_weight=text_knn_weight,
        visual_weight=visual_weight,
    )

    return ranked


MAX_CONTENT_TYPE_RATIO = 0.7  # No more than 70% of results from one content type


def diversify_results(
    ranked_items: list[RankedItem],
    max_per_video: int,
    target_count: int,
    content_types: list[str] | None = None,
) -> list[RankedItem]:
    if not ranked_items:
        return []
    
    total_candidates = len(ranked_items)
    unique_videos = len(set(item.video_id for item in ranked_items))
    
    effective_max = _compute_effective_max_per_video(
        max_per_video, target_count, total_candidates, unique_videos
    )
    
    video_counts: dict[str, int] = defaultdict(int)
    diversified: list[RankedItem] = []
    penalized_items: list[RankedItem] = []
    
    for item in ranked_items:
        if len(diversified) >= target_count:
            break
        
        if video_counts[item.video_id] < effective_max:
            diversified.append(item)
            video_counts[item.video_id] += 1
        else:
            item.diversification_penalty = True
            penalized_items.append(item)
    
    if len(diversified) < target_count and penalized_items:
        for item in penalized_items:
            if len(diversified) >= target_count:
                break
            diversified.append(item)

    mixed_search = (
        content_types is not None
        and "video" in content_types
        and "image" in content_types
    )
    if mixed_search and len(diversified) > 1:
        diversified = _balance_content_types(diversified, target_count)

    logger.debug(
        "diversification_applied",
        input_count=total_candidates,
        output_count=len(diversified),
        unique_videos=unique_videos,
        max_per_video=max_per_video,
        effective_max=effective_max,
        penalized_count=len([i for i in diversified if i.diversification_penalty]),
    )
    
    return diversified


def _balance_content_types(
    items: list[RankedItem],
    target_count: int,
) -> list[RankedItem]:
    """Enforce MAX_CONTENT_TYPE_RATIO cap across content types.

    When one content type exceeds 70% of results, excess items are moved
    to a deferred list and backfilled from the minority type. Items are
    never dropped — only reordered to promote diversity.
    """
    max_per_type = max(1, int(target_count * MAX_CONTENT_TYPE_RATIO))
    type_counts: dict[str, int] = defaultdict(int)
    balanced: list[RankedItem] = []
    deferred: list[RankedItem] = []

    for item in items:
        ct = item.source.get("content_type", "video")
        if type_counts[ct] < max_per_type:
            balanced.append(item)
            type_counts[ct] += 1
        else:
            deferred.append(item)

    for item in deferred:
        if len(balanced) >= target_count:
            break
        balanced.append(item)

    return balanced


def _compute_effective_max_per_video(
    max_per_video: int,
    target_count: int,
    total_candidates: int,
    unique_videos: int,
) -> int:
    if total_candidates <= target_count:
        return total_candidates
    
    if unique_videos == 1:
        return target_count
    
    if unique_videos < target_count // max_per_video:
        return max(max_per_video, target_count // unique_videos)
    
    return max_per_video
