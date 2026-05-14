"""Unit tests for mention_extractor.filter_by_dominance.

The dominance check catches BM25-matched scenes where "another selected
catalog's alias also appears as a substring in the same scene's
transcript/caption/OCR". If the primary-alias-hit / (primary + other)
ratio falls below threshold, that scene is dropped. Zero cost (no
extra OS queries).
"""

from __future__ import annotations

import pytest

from app.modules.shorts_auto_product.track_stt.mention_extractor import (
    filter_by_dominance,
)
from app.modules.shorts_auto_product.track_stt.models import MentionedScene


def _scene(
    scene_id: str,
    transcript: str = "",
    caption: str = "",
    ocr: str = "",
    score: float = 5.0,
) -> MentionedScene:
    return MentionedScene(
        scene_id=scene_id,
        start_ms=0,
        end_ms=10000,
        score=score,
        matched_field="transcript_raw",
        matched_aliases=[],
        transcript_text=transcript,
        caption_text=caption,
        ocr_text=ocr,
    )


def test_dominance_off_when_threshold_zero():
    """threshold=0 lets every scene pass (back-compat default)."""
    scenes = [_scene("s1", transcript="달심 주스 시원해요")]
    result = filter_by_dominance(
        scenes,
        primary_aliases=["달심"],
        other_aliases_groups=[["멜로멜로"]],
        threshold=0.0,
    )
    assert len(result) == 1
    assert result[0].scene_id == "s1"


def test_dominance_drops_scene_with_other_product_mention():
    """Drop scenes where another product's alias dominates."""
    scenes = [
        _scene(
            "s1",
            transcript="멜로멜로 정말 맛있고 멜로멜로 추천. 달심도 한 모금.",
        ),  # 멜로멜로 twice, 달심 once — — dominance = 1/3 ≈ 0.33 < 0.5
    ]
    result = filter_by_dominance(
        scenes,
        primary_aliases=["달심"],
        other_aliases_groups=[["멜로멜로"]],
        threshold=0.5,
    )
    assert result == []


def test_dominance_keeps_scene_with_only_primary():
    """Keep scenes that contain no other-product aliases at all."""
    scenes = [
        _scene("s1", transcript="달심 주스 정말 시원해요. 달심 진짜 추천."),
    ]
    result = filter_by_dominance(
        scenes,
        primary_aliases=["달심"],
        other_aliases_groups=[["멜로멜로"]],
        threshold=0.5,
    )
    assert len(result) == 1
    assert result[0].scene_id == "s1"


def test_dominance_threshold_boundary():
    """threshold=0.5 boundary: primary 2 / other 2 = 0.5 -> pass (>=)."""
    scenes = [
        _scene(
            "s1",
            transcript="달심 달심 멜로멜로 멜로멜로",
        ),
    ]
    result = filter_by_dominance(
        scenes,
        primary_aliases=["달심"],
        other_aliases_groups=[["멜로멜로"]],
        threshold=0.5,
    )
    assert len(result) == 1


def test_dominance_counts_across_fields():
    """Dominance is summed across transcript + caption + ocr."""
    scenes = [
        _scene(
            "s1",
            transcript="달심",
            caption="배경에 멜로멜로 음료가 보임",
            ocr="멜로멜로 PROMO",
        ),
    ]
    # primary 1, other 2 -> 1/(1+2) = 0.33 < 0.5 -> drop
    result = filter_by_dominance(
        scenes,
        primary_aliases=["달심"],
        other_aliases_groups=[["멜로멜로"]],
        threshold=0.5,
    )
    assert result == []


def test_dominance_no_other_groups_is_noop():
    """No other catalogs -> every scene passes (M=1 case)."""
    scenes = [_scene("s1", transcript="달심 주스")]
    result = filter_by_dominance(
        scenes,
        primary_aliases=["달심"],
        other_aliases_groups=[],
        threshold=0.5,
    )
    assert len(result) == 1


def test_dominance_case_folding():
    """English brand names are compared with case-folding."""
    scenes = [
        _scene("s1", transcript="GLOWMASK 좋아요", ocr="glowmask"),
    ]
    # primary GLOWMASK 2 (transcript + ocr), other 0 -> keep
    result = filter_by_dominance(
        scenes,
        primary_aliases=["glowmask"],  # lowercased input
        other_aliases_groups=[["멜로멜로"]],
        threshold=0.5,
    )
    assert len(result) == 1


def test_dominance_empty_primary_aliases_keeps_scene():
    """Empty primary aliases -> can't compute dominance, keep (defensive)."""
    scenes = [_scene("s1", transcript="아무 텍스트")]
    result = filter_by_dominance(
        scenes,
        primary_aliases=[],
        other_aliases_groups=[["멜로멜로"]],
        threshold=0.5,
    )
    assert len(result) == 1