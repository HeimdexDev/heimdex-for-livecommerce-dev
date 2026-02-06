from collections import defaultdict
from dataclasses import dataclass, field

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.search.normalize import get_normalized_char_count

logger = get_logger(__name__)

# Quality signal thresholds
MIN_TRANSCRIPT_CHARS = 20   # Very short transcripts get penalized
GOOD_TRANSCRIPT_CHARS = 100  # Full quality above this threshold
QUALITY_FLOOR = 0.7         # Minimum quality multiplier (never filter completely)


@dataclass
class RankedItem:
    doc_id: str
    video_id: str
    source: dict
    lexical_rank: int | None = None
    lexical_score: float | None = None
    vector_rank: int | None = None
    vector_score: float | None = None
    lexical_contribution: float = 0.0
    vector_contribution: float = 0.0
    quality_factor: float = 1.0
    fused_score: float = 0.0
    adjusted_score: float = 0.0
    diversification_penalty: bool = False


def rrf_score(rank: int | None, k: int = 60) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (k + rank)


def compute_quality_factor(source: dict) -> float:
    """
    Compute quality factor based on transcript character count.
    
    Fallback chain:
    1. transcript_char_count_normalized (pre-computed normalized)
    2. transcript_char_count (legacy, raw count)
    3. Compute from transcript text using get_normalized_char_count()
    
    Returns:
        Quality factor between QUALITY_FLOOR (0.7) and 1.0
    """
    char_count = source.get("transcript_char_count_normalized", 0)
    
    if char_count == 0:
        char_count = source.get("transcript_char_count", 0)
    
    if char_count == 0:
        transcript = source.get("transcript_raw", "") or source.get("transcript_norm", "")
        if transcript:
            char_count = get_normalized_char_count(transcript)
    
    if char_count >= GOOD_TRANSCRIPT_CHARS:
        return 1.0
    elif char_count <= MIN_TRANSCRIPT_CHARS:
        return QUALITY_FLOOR
    else:
        ratio = (char_count - MIN_TRANSCRIPT_CHARS) / (GOOD_TRANSCRIPT_CHARS - MIN_TRANSCRIPT_CHARS)
        return QUALITY_FLOOR + ratio * (1.0 - QUALITY_FLOOR)


def compute_weighted_rrf(
    lexical_results: list[dict],
    vector_results: list[dict],
    alpha: float,
) -> list[RankedItem]:
    settings = get_settings()
    k = settings.search_rrf_k
    
    items: dict[str, RankedItem] = {}
    
    for rank, hit in enumerate(lexical_results, start=1):
        doc_id = hit["_id"]
        video_id = hit["_source"].get("video_id", "")
        
        if doc_id not in items:
            items[doc_id] = RankedItem(
                doc_id=doc_id,
                video_id=video_id,
                source=hit["_source"],
            )
        
        items[doc_id].lexical_rank = rank
        items[doc_id].lexical_score = hit.get("_score", 0.0)
    
    for rank, hit in enumerate(vector_results, start=1):
        doc_id = hit["_id"]
        video_id = hit["_source"].get("video_id", "")
        
        if doc_id not in items:
            items[doc_id] = RankedItem(
                doc_id=doc_id,
                video_id=video_id,
                source=hit["_source"],
            )
        
        items[doc_id].vector_rank = rank
        items[doc_id].vector_score = hit.get("_score", 0.0)
    
    for item in items.values():
        lex_contribution = (1 - alpha) * rrf_score(item.lexical_rank, k)
        vec_contribution = alpha * rrf_score(item.vector_rank, k)
        item.lexical_contribution = lex_contribution
        item.vector_contribution = vec_contribution
        item.fused_score = lex_contribution + vec_contribution
        
        item.quality_factor = compute_quality_factor(item.source)
        item.adjusted_score = item.fused_score * item.quality_factor
    
    ranked = sorted(items.values(), key=lambda x: x.adjusted_score, reverse=True)
    
    logger.debug(
        "rrf_fusion_computed",
        total_candidates=len(ranked),
        lexical_count=len(lexical_results),
        vector_count=len(vector_results),
        alpha=alpha,
    )
    
    return ranked


def diversify_results(
    ranked_items: list[RankedItem],
    max_per_video: int,
    target_count: int,
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
