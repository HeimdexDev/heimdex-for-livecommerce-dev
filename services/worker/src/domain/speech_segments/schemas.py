"""Speech Segments 데이터 스키마 정의"""
from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class SpeechSegment:
    """단일 음성 구간"""
    start: float  # 시작 시간 (초)
    end: float    # 종료 시간 (초)
    text: str     # STT 결과 텍스트
    confidence: float = 0.0  # STT 신뢰도
    
    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class TaggedSegment(SpeechSegment):
    """태그가 붙은 음성 구간"""
    tags: list[str] = field(default_factory=list)
    tag_scores: dict[str, float] = field(default_factory=dict)


@dataclass
class RankedSegment(TaggedSegment):
    """랭킹이 매겨진 음성 구간"""
    rank: int = 0
    importance_score: float = 0.0


@dataclass
class PipelineResult:
    """파이프라인 전체 결과"""
    video_path: str
    segments: list[RankedSegment] = field(default_factory=list)
    total_duration: float = 0.0
    processing_time: float = 0.0
    status: str = "success"
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "segments": [asdict(s) for s in self.segments],
            "total_duration": self.total_duration,
            "processing_time": self.processing_time,
            "status": self.status,
            "error": self.error
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)