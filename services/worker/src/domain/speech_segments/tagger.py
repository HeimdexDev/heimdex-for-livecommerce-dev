"""Speech Tagger 모듈 - 음성 구간에 태그 부여
"""
from .schemas import SpeechSegment, TaggedSegment


# 카테고리별 키워드 사전
DEFAULT_KEYWORD_DICT = {
    "price": ["가격", "원", "할인", "쿠폰", "특가", "무료배송", "퍼센트", "프로"],
    "benefit": ["혜택", "증정", "사은품", "적립", "포인트"],
    "feature": ["기능", "효과", "성분", "사용", "지속력", "개선", "제형", "함유", "포함"],
    "bundle": ["구성", "세트", "1+1", "묶음", "용량", "리필", "본품"],
    "cta": ["지금", "바로", "구매", "링크", "장바구니", "라이브", "방송"],
    
    # 산업군에 따른 태깅 추가
}


class SpeechTagger:
    """키워드 사전 기반 음성 구간 태거"""
    
    def __init__(
        self,
        keyword_dict: dict[str, list[str]] | None = None,
        min_score_threshold: float = 0.0
    ):
        """
        Args:
            keyword_dict: 카테고리별 키워드 사전. None이면 기본 사전 사용
            min_score_threshold: 태그 부여를 위한 최소 점수 (0.0 = 키워드 1개라도 있으면 태그)
        """
        self.keyword_dict = keyword_dict or DEFAULT_KEYWORD_DICT
        self.min_score_threshold = min_score_threshold
        self.tag_categories = list(self.keyword_dict.keys())
    
    def _calculate_tag_scores(self, text: str) -> dict[str, float]:
        """텍스트에서 각 카테고리별 점수 계산"""
        text_lower = text.lower()
        scores = {}
        
        for category, keywords in self.keyword_dict.items():
            match_count = 0
            
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    match_count += 1
            
            if match_count > 0:
                scores[category] = match_count / len(keywords)
        
        return scores
    
    def _get_tags_from_scores(self, scores: dict[str, float]) -> list[str]:
        """점수를 기반으로 태그 목록 생성"""
        tags = [
            category for category, score in scores.items()
            if score > self.min_score_threshold
        ]
        tags.sort(key=lambda t: scores.get(t, 0), reverse=True)
        return tags
    
    def tag(self, segments: list[SpeechSegment]) -> list[TaggedSegment]:
        """음성 구간들에 태그를 부여"""
        tagged = []
        
        for seg in segments:
            tag_scores = self._calculate_tag_scores(seg.text)
            tags = self._get_tags_from_scores(tag_scores)
            
            tagged.append(TaggedSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                confidence=seg.confidence,
                tags=tags,
                tag_scores=tag_scores
            ))
        
        return tagged
    
    def add_keywords(self, category: str, keywords: list[str]) -> None:
        """카테고리에 키워드 추가"""
        if category not in self.keyword_dict:
            self.keyword_dict[category] = []
            self.tag_categories.append(category)
        
        self.keyword_dict[category].extend(keywords)
        self.keyword_dict[category] = list(set(self.keyword_dict[category]))