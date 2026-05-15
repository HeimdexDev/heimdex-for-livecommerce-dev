"""Unit tests for ``shorts_render.subtitles_export``.

Pure-function tests — no fixtures, no HTTP, no DB. Covers:

* SRT formatting: header-less, comma-millisecond separator, blank-line
  block separation, trailing newline.
* WebVTT formatting: WEBVTT header, dot-millisecond separator,
  optional-cue-id omission.
* Timestamp boundary cases: hour rollover, sub-second precision,
  negative input clamps to 0.
* Filtering: out-of-order input, zero-duration cues, blank/whitespace
  text, mistyped fields all drop quietly.
"""

from __future__ import annotations

from app.modules.shorts_render.subtitles_export import (
    subtitles_to_srt,
    subtitles_to_vtt,
)


def test_srt_basic_two_cues():
    out = subtitles_to_srt(
        [
            {"text": "안녕하세요", "start_ms": 0, "end_ms": 1500},
            {"text": "반가워요", "start_ms": 1500, "end_ms": 3200},
        ]
    )
    assert out == (
        "1\n"
        "00:00:00,000 --> 00:00:01,500\n"
        "안녕하세요\n"
        "\n"
        "2\n"
        "00:00:01,500 --> 00:00:03,200\n"
        "반가워요\n"
    )


def test_vtt_basic_two_cues_has_header_and_dot_separator():
    out = subtitles_to_vtt(
        [
            {"text": "first", "start_ms": 250, "end_ms": 1000},
            {"text": "second", "start_ms": 1000, "end_ms": 2750},
        ]
    )
    assert out == (
        "WEBVTT\n"
        "\n"
        "00:00:00.250 --> 00:00:01.000\n"
        "first\n"
        "\n"
        "00:00:01.000 --> 00:00:02.750\n"
        "second\n"
    )


def test_srt_empty_input_returns_empty_string():
    # No cues = empty body. Caller decides whether to 200-empty or 404.
    assert subtitles_to_srt([]) == ""


def test_vtt_empty_input_still_emits_header():
    # WebVTT requires the header; downstream players reject body-only.
    assert subtitles_to_vtt([]) == "WEBVTT\n"


def test_srt_sorts_out_of_order_cues_by_start_ms():
    out = subtitles_to_srt(
        [
            {"text": "second", "start_ms": 5000, "end_ms": 6000},
            {"text": "first", "start_ms": 0, "end_ms": 4000},
        ]
    )
    # Cue 1 must be the chronologically-first text, regardless of input
    # order — protects against PATCH bodies that drift after edits.
    assert out.startswith("1\n00:00:00,000 --> 00:00:04,000\nfirst\n")
    assert "2\n00:00:05,000 --> 00:00:06,000\nsecond\n" in out


def test_srt_drops_zero_duration_and_blank_cues():
    out = subtitles_to_srt(
        [
            {"text": "keep", "start_ms": 0, "end_ms": 1000},
            {"text": "zero-len", "start_ms": 2000, "end_ms": 2000},
            {"text": "negative-len", "start_ms": 3000, "end_ms": 2500},
            {"text": "   ", "start_ms": 4000, "end_ms": 5000},
            {"text": "", "start_ms": 5000, "end_ms": 6000},
        ]
    )
    # Only "keep" survives → renumbered as cue 1, no cue 2.
    assert out == "1\n00:00:00,000 --> 00:00:01,000\nkeep\n"


def test_srt_drops_malformed_entries():
    out = subtitles_to_srt(
        [
            {"text": "ok", "start_ms": 0, "end_ms": 500},
            {"text": "no-times"},  # missing start/end
            {"text": 42, "start_ms": 600, "end_ms": 700},  # text not str
            {"start_ms": 800, "end_ms": 900},  # missing text
            "not-a-mapping",  # type: ignore[list-item]
            {"text": "bad-times", "start_ms": "0", "end_ms": "500"},  # str not int
        ]
    )
    # Only the well-formed entry survives.
    assert out == "1\n00:00:00,000 --> 00:00:00,500\nok\n"


def test_srt_timestamp_hour_rollover():
    # 1h 23m 45.678s → 01:23:45,678
    ms = (3600 + 23 * 60 + 45) * 1000 + 678
    out = subtitles_to_srt([{"text": "long", "start_ms": ms, "end_ms": ms + 1}])
    assert "01:23:45,678 --> 01:23:45,679" in out


def test_srt_timestamp_negative_clamps_to_zero():
    # Defensive — ought never happen, but a stray client edit
    # shouldn't poison the file with garbage like ``-1:59:59,...``.
    out = subtitles_to_srt(
        [{"text": "guarded", "start_ms": -500, "end_ms": -100}]
    )
    # Negative end <= negative start by spec but both clamp to 0,
    # making it zero-duration after clamping → dropped. End-of-test:
    # output is empty, NOT corrupt.
    assert out == ""


def test_srt_ignores_extra_keys_like_style_and_template_id():
    # ``input_spec.subtitles`` rows include style + template_id — the
    # SRT format has no place for them; serializer must not choke.
    out = subtitles_to_srt(
        [
            {
                "text": "styled",
                "start_ms": 0,
                "end_ms": 1000,
                "style": {"font_color": "#000000", "font_size_px": 36},
                "template_id": "tmpl_abc",
            }
        ]
    )
    assert out == "1\n00:00:00,000 --> 00:00:01,000\nstyled\n"


def test_srt_preserves_internal_whitespace_in_text():
    # ``strip()`` only trims leading/trailing — internal Korean spaces,
    # punctuation, and newlines stay. (Multi-line cue text is legal SRT.)
    out = subtitles_to_srt(
        [{"text": "  안녕  하세요\n반가워요  ", "start_ms": 0, "end_ms": 1000}]
    )
    assert "안녕  하세요\n반가워요" in out
