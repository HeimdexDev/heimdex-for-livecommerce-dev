"""Word-timed subtitle chunker behaviour."""

from __future__ import annotations

import pytest

from app.lib.subtitle_chunking.word_to_subtitle import Subtitle, chunk_words
from app.lib.whisper_transcribe.schemas import WhisperWord


def _w(text: str, start_ms: int, end_ms: int) -> WhisperWord:
    return WhisperWord(word=text, start_ms=start_ms, end_ms=end_ms)


class TestEdgeCases:
    def test_empty_input_returns_empty(self) -> None:
        assert chunk_words([]) == []

    def test_invalid_max_chars_raises(self) -> None:
        with pytest.raises(ValueError, match="max_chars"):
            chunk_words([_w("x", 0, 100)], max_chars=0)

    def test_invalid_gap_raises(self) -> None:
        with pytest.raises(ValueError, match="max_gap_ms"):
            chunk_words([_w("x", 0, 100)], max_gap_ms=-1)

    def test_invalid_min_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="min_duration_ms"):
            chunk_words([_w("x", 0, 1000)], min_duration_ms=-1)


class TestBasicChunking:
    def test_single_word_short_returns_one_subtitle(self) -> None:
        result = chunk_words([_w("안녕하세요", 0, 1000)])
        assert result == [Subtitle(start_ms=0, end_ms=1000, text="안녕하세요")]

    def test_two_words_within_limits_collapse_to_one_chunk(self) -> None:
        result = chunk_words(
            [_w("안녕", 0, 400), _w("하세요", 450, 900)],
            max_chars=25,
            max_gap_ms=500,
        )
        assert len(result) == 1
        assert result[0].text == "안녕 하세요"
        assert result[0].start_ms == 0
        assert result[0].end_ms == 900

    def test_words_join_with_single_space(self) -> None:
        result = chunk_words(
            [_w("hello", 0, 400), _w("world", 450, 900)],
        )
        assert result[0].text == "hello world"


class TestCharLimitBoundary:
    def test_exceeds_max_chars_starts_new_chunk(self) -> None:
        # max_chars=10. "abcde fghij" = 11 chars (with space), forces split.
        result = chunk_words(
            [
                _w("abcde", 0, 400),
                _w("fghij", 410, 900),
            ],
            max_chars=10,
        )
        assert len(result) == 2
        assert result[0].text == "abcde"
        assert result[1].text == "fghij"

    def test_single_oversize_word_stays_one_chunk(self) -> None:
        # We never split inside a word.
        result = chunk_words(
            [_w("supercalifragilisticexpialidocious", 0, 1000)],
            max_chars=10,
        )
        assert len(result) == 1
        assert result[0].text == "supercalifragilisticexpialidocious"


class TestGapBoundary:
    def test_silence_gap_starts_new_chunk(self) -> None:
        # 600ms gap > default 500ms — new chunk.
        result = chunk_words(
            [
                _w("first", 0, 400),
                _w("second", 1000, 1500),  # 600ms gap
            ],
        )
        assert len(result) == 2
        assert result[0].text == "first"
        assert result[1].text == "second"

    def test_gap_at_threshold_does_not_split(self) -> None:
        # Exactly at max_gap_ms (not strictly greater) — same chunk.
        result = chunk_words(
            [
                _w("first", 0, 400),
                _w("second", 900, 1300),  # 500ms gap = max_gap_ms
            ],
            max_gap_ms=500,
        )
        assert len(result) == 1


class TestSentenceEndBoundary:
    def test_period_terminates_chunk(self) -> None:
        result = chunk_words(
            [
                _w("끝.", 0, 500),
                _w("다음", 600, 1000),
            ],
        )
        assert len(result) == 2
        assert result[0].text == "끝."
        assert result[1].text == "다음"

    def test_question_mark_terminates_chunk(self) -> None:
        result = chunk_words(
            [
                _w("정말?", 0, 500),
                _w("좋아", 600, 1000),
            ],
        )
        assert len(result) == 2

    def test_korean_full_stop_terminates_chunk(self) -> None:
        result = chunk_words(
            [
                _w("안녕。", 0, 500),
                _w("다음", 600, 1000),
            ],
        )
        assert len(result) == 2


class TestValidationPass:
    def test_drops_sub_min_duration_chunk(self) -> None:
        # 50ms span < default 300ms minimum — dropped.
        result = chunk_words(
            [_w("blip", 100, 150)],
            min_duration_ms=300,
        )
        assert result == []

    def test_keeps_chunk_at_min_duration(self) -> None:
        result = chunk_words(
            [_w("ok", 0, 300)],
            min_duration_ms=300,
        )
        assert len(result) == 1

    def test_clamps_overlap_with_prior_chunk(self) -> None:
        # Two chunks (forced via period) where second starts before
        # first ends. Clamp pushes second forward.
        result = chunk_words(
            [
                _w("first.", 0, 1000),
                _w("second", 800, 1500),  # starts before first ends
            ],
        )
        assert len(result) == 2
        assert result[0].end_ms == 1000
        # Second start clamped to >= first end
        assert result[1].start_ms >= result[0].end_ms

    def test_timeline_clamp_truncates_end(self) -> None:
        result = chunk_words(
            [_w("hello", 0, 5000)],
            timeline_clamp_ms=3000,
        )
        assert len(result) == 1
        assert result[0].end_ms == 3000

    def test_timeline_clamp_drops_chunk_made_too_short(self) -> None:
        # Chunk would have 5000ms duration; clamp brings it to 100ms;
        # min_duration_ms=300 drops it.
        result = chunk_words(
            [_w("hello", 4900, 9900)],
            timeline_clamp_ms=5000,
            min_duration_ms=300,
        )
        assert result == []


class TestKoreanRealism:
    def test_korean_livecommerce_phrase(self) -> None:
        words = [
            _w("안녕하세요", 0, 600),
            _w("여러분", 700, 1100),
            _w("오늘은", 1200, 1700),
            _w("특가상품을", 1800, 2400),
            _w("소개해드릴게요.", 2500, 3500),
        ]
        result = chunk_words(words, max_chars=25)
        # All chunks within char limit
        for sub in result:
            assert len(sub.text) <= 25
        # Chronological, no overlap
        for a, b in zip(result, result[1:]):
            assert a.end_ms <= b.start_ms
        # Total text covers all words
        joined = " ".join(s.text for s in result)
        assert "안녕하세요" in joined
        assert "소개해드릴게요." in joined

    def test_long_run_produces_multiple_chunks(self) -> None:
        # 10 words, ~50 chars total → multiple chunks at max_chars=25.
        words = [_w(f"word{i:02d}", i * 200, i * 200 + 150) for i in range(10)]
        result = chunk_words(words, max_chars=25, max_gap_ms=100)
        assert len(result) >= 2

    def test_outputs_chronological(self) -> None:
        words = [
            _w("a", 0, 400),
            _w("b.", 500, 900),
            _w("c", 1100, 1500),
            _w("d", 1600, 2000),
        ]
        result = chunk_words(words)
        # Verify monotonic non-overlap
        for i in range(len(result) - 1):
            assert result[i].end_ms <= result[i + 1].start_ms
