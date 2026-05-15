"""Invariants for Whisper data shapes."""

from __future__ import annotations

import pytest

from app.lib.whisper_transcribe.schemas import WhisperResult, WhisperWord


class TestWhisperWord:
    def test_valid_word_constructs(self) -> None:
        w = WhisperWord(word="안녕하세요", start_ms=100, end_ms=850)
        assert w.word == "안녕하세요"
        assert w.start_ms == 100
        assert w.end_ms == 850

    def test_zero_duration_word_is_allowed(self) -> None:
        w = WhisperWord(word="hi", start_ms=500, end_ms=500)
        assert w.end_ms == w.start_ms

    @pytest.mark.parametrize("empty", ["", "   ", "\t", "\n"])
    def test_empty_word_raises(self, empty: str) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            WhisperWord(word=empty, start_ms=0, end_ms=100)

    def test_negative_start_ms_raises(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            WhisperWord(word="x", start_ms=-1, end_ms=100)

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >="):
            WhisperWord(word="x", start_ms=200, end_ms=100)

    def test_frozen(self) -> None:
        w = WhisperWord(word="x", start_ms=0, end_ms=100)
        with pytest.raises((AttributeError, TypeError)):
            w.start_ms = 50  # type: ignore[misc]


class TestWhisperResult:
    def test_constructs_with_all_fields(self) -> None:
        words = (
            WhisperWord(word="안녕", start_ms=0, end_ms=400),
            WhisperWord(word="하세요", start_ms=400, end_ms=900),
        )
        r = WhisperResult(
            words=words,
            text="안녕 하세요",
            language="ko",
            duration_seconds=1.0,
            cost_usd=0.0001,
            latency_ms=450,
        )
        assert r.words == words
        assert r.text == "안녕 하세요"
        assert r.language == "ko"
        assert r.duration_seconds == 1.0
        assert r.cost_usd == 0.0001
        assert r.latency_ms == 450

    def test_empty_words_is_valid(self) -> None:
        r = WhisperResult(
            words=(),
            text="",
            language="ko",
            duration_seconds=0.5,
            cost_usd=0.00005,
            latency_ms=200,
        )
        assert r.words == ()
        assert r.text == ""

    def test_frozen(self) -> None:
        r = WhisperResult(
            words=(),
            text="",
            language="ko",
            duration_seconds=0.5,
            cost_usd=0.0,
            latency_ms=100,
        )
        with pytest.raises((AttributeError, TypeError)):
            r.cost_usd = 1.0  # type: ignore[misc]
