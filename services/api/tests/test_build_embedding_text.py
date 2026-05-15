"""
Unit tests for build_embedding_text() helper (AD-2: caption-first embedding).

Tests cover:
1. Caption-first ordering
2. Character limits (transcript 500, ocr 200)
3. Empty/missing parts are skipped
4. All empty returns empty string
5. Single-field inputs

Run with: pytest tests/test_build_embedding_text.py -v
"""
import pytest

from app.modules.ingest.service import (
    build_embedding_text,
    _TRANSCRIPT_EMBED_LIMIT,
    _OCR_EMBED_LIMIT,
)


class TestBuildEmbeddingText:
    """Tests for the module-level build_embedding_text() helper."""

    def test_all_three_fields(self):
        """Caption comes first, then transcript, then OCR."""
        result = build_embedding_text(
            transcript_norm="transcript here",
            ocr_norm="ocr here",
            caption_norm="caption here",
        )
        assert result == "caption here transcript here ocr here"

    def test_caption_first_ordering(self):
        """Even with long transcript, caption appears first."""
        result = build_embedding_text(
            transcript_norm="B" * 100,
            ocr_norm="C" * 50,
            caption_norm="A" * 30,
        )
        parts = result.split(" ")
        # Caption part starts with 'A', transcript with 'B', ocr with 'C'
        assert parts[0].startswith("A")
        assert parts[1].startswith("B")
        assert parts[2].startswith("C")

    def test_transcript_limit(self):
        """Transcript is truncated to _TRANSCRIPT_EMBED_LIMIT chars."""
        long_transcript = "x" * 1000
        result = build_embedding_text(
            transcript_norm=long_transcript,
            ocr_norm="",
            caption_norm="",
        )
        assert len(result) == _TRANSCRIPT_EMBED_LIMIT
        assert result == "x" * _TRANSCRIPT_EMBED_LIMIT

    def test_ocr_limit(self):
        """OCR is truncated to _OCR_EMBED_LIMIT chars."""
        long_ocr = "y" * 500
        result = build_embedding_text(
            transcript_norm="",
            ocr_norm=long_ocr,
            caption_norm="",
        )
        assert len(result) == _OCR_EMBED_LIMIT
        assert result == "y" * _OCR_EMBED_LIMIT

    def test_caption_not_limited(self):
        """Caption is NOT truncated (full text used)."""
        long_caption = "z" * 2000
        result = build_embedding_text(
            transcript_norm="",
            ocr_norm="",
            caption_norm=long_caption,
        )
        assert len(result) == 2000

    def test_all_empty_returns_empty_string(self):
        """All empty inputs produce empty string."""
        result = build_embedding_text(
            transcript_norm="",
            ocr_norm="",
            caption_norm="",
        )
        assert result == ""

    def test_only_caption(self):
        """Only caption provided."""
        result = build_embedding_text(
            transcript_norm="",
            ocr_norm="",
            caption_norm="just caption",
        )
        assert result == "just caption"

    def test_only_transcript(self):
        """Only transcript provided."""
        result = build_embedding_text(
            transcript_norm="just transcript",
            ocr_norm="",
            caption_norm="",
        )
        assert result == "just transcript"

    def test_only_ocr(self):
        """Only OCR provided."""
        result = build_embedding_text(
            transcript_norm="",
            ocr_norm="just ocr",
            caption_norm="",
        )
        assert result == "just ocr"

    def test_caption_and_transcript_no_ocr(self):
        """Caption + transcript, no OCR."""
        result = build_embedding_text(
            transcript_norm="transcript",
            ocr_norm="",
            caption_norm="caption",
        )
        assert result == "caption transcript"

    def test_limits_are_correct_values(self):
        """Verify the limit constants have expected values."""
        assert _TRANSCRIPT_EMBED_LIMIT == 500
        assert _OCR_EMBED_LIMIT == 200
