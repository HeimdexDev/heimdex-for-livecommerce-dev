from src.tasks.subtitle_parser import (
    SubtitleCue,
    clean_subtitle_text,
    map_cues_to_scenes,
    parse_vtt,
)


def test_parse_vtt_basic_and_korean_text():
    content = """WEBVTT

00:00:00.000 --> 00:00:01.000
안녕하세요

00:00:01.000 --> 00:00:02.000
반갑습니다
"""
    cues = parse_vtt(content)
    assert len(cues) == 2
    assert cues[0] == SubtitleCue(start_ms=0, end_ms=1000, text="안녕하세요")


def test_parse_vtt_empty():
    assert parse_vtt("") == []


def test_clean_subtitle_strips_music_and_duplicate_lines():
    text = "[음악] ♪ 안녕 안녕    세상"
    assert clean_subtitle_text(text) == "안녕 세상"


def test_map_cues_to_scenes_basic_mapping():
    cues = [
        SubtitleCue(0, 900, "첫 장면"),
        SubtitleCue(1100, 1900, "둘째 장면"),
    ]
    result = map_cues_to_scenes(cues, [0, 1000, 2000])
    assert result == {0: "첫 장면", 1: "둘째 장면"}


def test_map_cues_to_scenes_overlapping_cues():
    cues = [
        SubtitleCue(900, 1100, "경계 자막"),
        SubtitleCue(1200, 1800, "다음 자막"),
    ]
    result = map_cues_to_scenes(cues, [(0, 1000), (1000, 2000)])
    assert result[1] == "경계 자막 다음 자막"
