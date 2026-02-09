"""Ranker 모듈 - 태그된 구간에 중요도 순위 부여"""
from .schemas import TaggedSegment, RankedSegment


class SegmentRanker:
    """태그된 음성 구간에 중요도 순위를 부여"""
    
    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or {
            "highlight": 1.0,
            "important": 0.8,
            "question": 0.6,
            "answer": 0.5,
            "transition": 0.2
        }
    
    def rank(self, segments: list[TaggedSegment]) -> list[RankedSegment]:
        """
        태그된 구간들에 중요도 순위 부여
        
        Args:
            segments: TaggedSegment 리스트
            
        Returns:
            RankedSegment 리스트 (순위 순으로 정렬됨)
        """
        # TODO: 실제 랭킹 로직 구현
        ranked = []
        for i, seg in enumerate(segments):
            ranked.append(RankedSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                confidence=seg.confidence,
                tags=seg.tags,
                tag_scores=seg.tag_scores,
                rank=i + 1,
                importance_score=0.0
            ))
        return ranked