"""Speech Segments 도메인 모듈
음성 구간 추출, 태깅, 랭킹을 위한 파이프라인
"""
from .schemas import (
    SpeechSegment,
    TaggedSegment,
    RankedSegment,
    PipelineResult
)
from .stt import STTProcessor
from .tagger import SpeechTagger
from .ranker import SegmentRanker
from .pipeline import SpeechSegmentsPipeline

__all__ = [
    # Schemas
    "SpeechSegment",
    "TaggedSegment", 
    "RankedSegment",
    "PipelineResult",
    # Processors
    "STTProcessor",
    "SpeechTagger",
    "SegmentRanker",
    # Pipeline
    "SpeechSegmentsPipeline",
]