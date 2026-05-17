"""SpeechTagger unit tests — fixed to match actual tagger API.

These tests import from the backward-compatible shim, which re-exports from
heimdex-media-contracts.  The canonical test suite lives in
heimdex-media-contracts/tests/test_speech_tagger.py.
"""
import pytest
import sys
from pathlib import Path

# Allow running standalone without package install
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "services" / "worker" / "src" / "domain"))

from speech_segments import SpeechSegment, TaggedSegment, SpeechTagger


class TestSpeechTagger:
    """SpeechTagger 테스트"""

    def test_init_default_categories(self):
        """기본 태그 카테고리로 초기화"""
        tagger = SpeechTagger()
        assert len(tagger.tag_categories) > 0
        # Actual defaults: price, benefit, feature, bundle, cta
        assert "price" in tagger.tag_categories
        assert "cta" in tagger.tag_categories

    def test_init_custom_keyword_dict(self):
        """커스텀 키워드 사전으로 초기화"""
        custom = {"intro": ["시작", "안녕"], "outro": ["끝", "감사"]}
        tagger = SpeechTagger(keyword_dict=custom)
        assert set(tagger.tag_categories) == {"intro", "outro"}

    def test_tag_empty_segments(self):
        """빈 세그먼트 리스트 태깅"""
        tagger = SpeechTagger()
        result = tagger.tag([])
        assert result == []

    def test_tag_single_segment(self):
        """단일 세그먼트 태깅"""
        tagger = SpeechTagger()
        segment = SpeechSegment(
            start=0.0,
            end=5.0,
            text="Hello world",
            confidence=0.95,
        )
        result = tagger.tag([segment])

        assert len(result) == 1
        assert isinstance(result[0], TaggedSegment)
        assert result[0].start == 0.0
        assert result[0].end == 5.0
        assert result[0].text == "Hello world"

    def test_tag_preserves_original_data(self):
        """태깅 시 원본 데이터 보존"""
        tagger = SpeechTagger()
        segments = [
            SpeechSegment(start=0.0, end=3.0, text="First", confidence=0.9),
            SpeechSegment(start=3.0, end=6.0, text="Second", confidence=0.85),
        ]
        result = tagger.tag(segments)

        assert len(result) == 2
        assert result[0].confidence == 0.9
        assert result[1].confidence == 0.85


if __name__ == "__main__":
    pytest.main([__file__, "-v"])