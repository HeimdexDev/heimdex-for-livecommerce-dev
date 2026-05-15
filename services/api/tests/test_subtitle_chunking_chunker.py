"""Character-aware subtitle chunker behaviour."""

from __future__ import annotations

import pytest

from app.lib.subtitle_chunking.chunker import (
    MAX_SUBTITLE_CHARS,
    chunk_subtitle_text,
    merge_chunks_to_count,
)


class TestChunkSubtitleText:
    @pytest.mark.parametrize("empty", ["", "   ", "\t\n", None])
    def test_empty_returns_empty(self, empty: str | None) -> None:
        assert chunk_subtitle_text(empty or "") == []

    def test_short_text_returned_as_single_chunk(self) -> None:
        assert chunk_subtitle_text("안녕하세요") == ["안녕하세요"]

    def test_chunk_at_max_chars_is_single(self) -> None:
        text = "a" * MAX_SUBTITLE_CHARS
        assert chunk_subtitle_text(text) == [text]

    def test_long_korean_splits_at_sentence(self) -> None:
        text = "안녕하세요 반갑습니다. 오늘 날씨가 정말 좋네요. 산책하기 좋은 날입니다."
        chunks = chunk_subtitle_text(text)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c) <= MAX_SUBTITLE_CHARS

    def test_long_korean_splits_at_clause(self) -> None:
        # Single sentence with clause boundaries (commas + connectives).
        text = "오늘 시간이 없으니까 빨리 먹고, 다음 가게로 이동해야 합니다."
        chunks = chunk_subtitle_text(text)
        assert all(len(c) <= MAX_SUBTITLE_CHARS for c in chunks)
        assert len(chunks) >= 2

    def test_oversize_clause_falls_back_to_eojeol_pack(self) -> None:
        # No internal sentence/clause boundaries — trips the eojeol fallback.
        text = "이번주 한정세일 특가상품 다이슨 청소기 김치냉장고 모두모두 구매하세요"
        chunks = chunk_subtitle_text(text)
        assert all(len(c) <= MAX_SUBTITLE_CHARS for c in chunks)
        # No empty chunks
        assert all(c.strip() for c in chunks)

    def test_latin_punctuation_splits(self) -> None:
        text = "Welcome to the show. Today we have great products. Let's see them all!"
        chunks = chunk_subtitle_text(text)
        assert all(len(c) <= MAX_SUBTITLE_CHARS for c in chunks)
        assert len(chunks) >= 2

    def test_all_chunks_are_stripped(self) -> None:
        text = "  여러분   안녕하세요   반갑습니다   오늘은   특가상품을   소개합니다  "
        chunks = chunk_subtitle_text(text)
        for c in chunks:
            assert c == c.strip()

    def test_pathological_single_long_token_returns_unsliced(self) -> None:
        # Documents existing behavior: a single token with no internal
        # whitespace, sentence-end, or clause boundary cannot be
        # broken. The chunker returns it as one oversize chunk rather
        # than mid-word slicing. The leading-slice fallback at the
        # bottom of the function only fires when chunks ended up
        # EMPTY — which doesn't happen here because eojeol-pack
        # accumulates the whole token into ``current``.
        #
        # PR 3 must preserve this: subtitle_generator.py callers
        # already rely on no mid-word truncation.
        text = "a" * 30
        chunks = chunk_subtitle_text(text)
        assert chunks == [text]

    def test_empty_strip_returns_empty(self) -> None:
        assert chunk_subtitle_text("\n\n\t  ") == []


class TestMergeChunksToCount:
    def test_target_zero_returns_input(self) -> None:
        assert merge_chunks_to_count(["a", "b"], 0) == ["a", "b"]

    def test_target_equals_len_is_noop(self) -> None:
        chunks = ["one", "two", "three"]
        assert merge_chunks_to_count(chunks, 3) == chunks

    def test_target_exceeds_len_is_noop(self) -> None:
        chunks = ["one", "two"]
        assert merge_chunks_to_count(chunks, 5) == chunks

    def test_merges_shortest_adjacent_pair(self) -> None:
        # "a" + "b" is shortest pair; merges first.
        chunks = ["a", "b", "looooong"]
        assert merge_chunks_to_count(chunks, 2) == ["a b", "looooong"]

    def test_merges_down_to_one(self) -> None:
        result = merge_chunks_to_count(["a", "b", "c", "d"], 1)
        assert len(result) == 1
        assert "a" in result[0] and "d" in result[0]

    def test_empty_input_returns_empty(self) -> None:
        assert merge_chunks_to_count([], 5) == []
