"""Unit tests for the primary_catalog_match signal on chunk_scorer + ChunkScore.

Wave 2.3 (chunk-level LLM catalog match) — the chunk_scorer LLM makes a
semantic call on "is this chunk really about the primary catalog?".
Chunks below the threshold are rejected.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.shorts_auto_product.track_stt import chunk_scorer
from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionSegment,
    MentionedScene,
)


# ---------- ChunkScore model ----------


def test_chunk_score_has_primary_catalog_match_default():
    """ChunkScore has a primary_catalog_match field, default=1.0 (back-compat)."""
    s = ChunkScore(hook_score=0.7, has_cta=False, importance_score=0.8)
    assert s.primary_catalog_match == 1.0


def test_chunk_score_accepts_primary_catalog_match():
    """primary_catalog_match can be set explicitly."""
    s = ChunkScore(
        hook_score=0.7, has_cta=False, importance_score=0.8,
        primary_catalog_match=0.3,
    )
    assert s.primary_catalog_match == 0.3


# ---------- chunk_scorer LLM integration ----------


def _scene(scene_id: str = "s1", transcript: str = ""):
    return MentionedScene(
        scene_id=scene_id, start_ms=0, end_ms=5000,
        score=5.0, matched_field="transcript_raw",
        matched_aliases=[], transcript_text=transcript,
    )


def _segment(scenes, start_ms=0, end_ms=15_000):
    return MentionSegment(scenes=list(scenes), start_ms=start_ms, end_ms=end_ms)


def _mock_openai_response(content: str):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


@pytest.mark.asyncio
async def test_score_segment_chunks_returns_catalog_match():
    """Returns primary_catalog_match from the response when primary_catalog_name is given."""
    seg = _segment([_scene(transcript="달심 진짜 시원해요")])
    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(return_value=_mock_openai_response(
        '{"scores":[{"hook_score":0.7,"has_cta":false,"importance_score":0.8,"primary_catalog_match":0.9}]}'
    ))
    chunks = await chunk_scorer.score_segment_chunks(
        segment=seg, openai_client=fake_openai,
        primary_catalog_name="달심 주스",
        primary_aliases=["달심"],
        other_catalog_names=["멜로멜로 음료"],
    )
    assert len(chunks) == 1
    assert chunks[0].score.primary_catalog_match == 0.9


@pytest.mark.asyncio
async def test_score_segment_chunks_threshold_filters_low_match():
    """When catalog_match_threshold > 0, chunks with primary_catalog_match < threshold are rejected."""
    seg = _segment([_scene(transcript="멜로멜로 좋고 달심도")])
    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(return_value=_mock_openai_response(
        '{"scores":[{"hook_score":0.7,"has_cta":false,"importance_score":0.6,"primary_catalog_match":0.2}]}'
    ))
    chunks = await chunk_scorer.score_segment_chunks(
        segment=seg, openai_client=fake_openai,
        primary_catalog_name="달심 주스",
        primary_aliases=["달심"],
        other_catalog_names=["멜로멜로 음료"],
        catalog_match_threshold=0.5,
    )
    assert chunks == []  # 0.2 < 0.5 -> reject


@pytest.mark.asyncio
async def test_other_catalog_names_passed_to_llm():
    """Primary + other catalog names are included in the LLM call messages."""
    seg = _segment([_scene(transcript="달심 좋아요")])
    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(return_value=_mock_openai_response(
        '{"scores":[{"hook_score":0.5,"has_cta":false,"importance_score":0.5,"primary_catalog_match":0.8}]}'
    ))
    await chunk_scorer.score_segment_chunks(
        segment=seg, openai_client=fake_openai,
        primary_catalog_name="달심 주스",
        primary_aliases=["달심"],
        other_catalog_names=["멜로멜로 음료", "리프레시 차"],
    )
    messages = fake_openai.chat.completions.create.await_args.kwargs["messages"]
    payload_str = str(messages)
    assert "달심 주스" in payload_str
    assert "멜로멜로 음료" in payload_str
    assert "리프레시 차" in payload_str


@pytest.mark.asyncio
async def test_backcompat_no_catalog_info():
    """With primary_catalog_name=None, catalog match isn't requested and defaults to 1.0."""
    seg = _segment([_scene(transcript="아무 텍스트")])
    fake_openai = MagicMock()
    # Legacy response schema (no primary_catalog_match) — back-compat fallback
    fake_openai.chat.completions.create = AsyncMock(return_value=_mock_openai_response(
        '{"scores":[{"hook_score":0.5,"has_cta":false,"importance_score":0.5}]}'
    ))
    chunks = await chunk_scorer.score_segment_chunks(
        segment=seg, openai_client=fake_openai,
    )
    assert len(chunks) == 1
    assert chunks[0].score.primary_catalog_match == 1.0


@pytest.mark.asyncio
async def test_heuristic_fallback_default_match_one():
    """When the LLM call fails, the heuristic returns primary_catalog_match=1.0 (passes filter)."""
    seg = _segment([_scene(transcript="텍스트")])
    fake_openai = MagicMock()
    fake_openai.chat.completions.create = AsyncMock(side_effect=Exception("LLM down"))
    chunks = await chunk_scorer.score_segment_chunks(
        segment=seg, openai_client=fake_openai,
        primary_catalog_name="달심",
        primary_aliases=["달심"],
        other_catalog_names=["멜로멜로"],
        catalog_match_threshold=0.5,
    )
    # heuristic baseline = match 1.0 -> passes threshold 0.5 -> survives
    assert len(chunks) == 1
    assert chunks[0].score.primary_catalog_match == 1.0


def test_settings_chunk_catalog_match_default():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.auto_shorts_product_v2_chunk_catalog_match_threshold == 0.0


def test_settings_chunk_catalog_match_env_override(monkeypatch):
    monkeypatch.setenv(
        "AUTO_SHORTS_PRODUCT_V2_CHUNK_CATALOG_MATCH_THRESHOLD", "0.6"
    )
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.auto_shorts_product_v2_chunk_catalog_match_threshold == 0.6