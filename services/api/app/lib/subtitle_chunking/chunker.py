"""Character-aware Korean+Latin subtitle chunker.

Extracted byte-identically from the original location:
``app/modules/shorts_auto_product/track_stt/subtitle_generator.py``.
PR 3 will update that file to import from here. Until then, both
copies coexist — :file:`tests/test_subtitle_chunking_regression.py`
asserts they produce identical output.

Design (mirrors the FE ``chunkSubtitleText`` in
``services/web/src/features/shorts-editor/hooks/useEditorState.ts``):

* 25-char target per row (≈ 5-7 Korean eojeol; reads in 1-2s at
  livecommerce pace).
* Two-pass split — sentence boundaries first, then Korean clause
  boundaries (conjunctive endings + commas) within oversize sentences;
  eojeol-greedy fallback for runaway clauses without internal
  boundaries.

Pure functions. No I/O. Trivially testable.
"""

from __future__ import annotations

import re

# Sentence-ending patterns (Korean + Latin) — primary split.
# Python's ``re`` requires fixed-width lookbehinds, so we split into
# two alternatives instead of the FE's variable-width form.
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<=[.!?。])\s+|(?<=[요다죠음네까게세지])\s+(?=[가-힣A-Za-z0-9])"
)

# Korean clause-boundary patterns — secondary split for finer chunks.
# Conjunctive endings ("는데", "면서요", "이기 때문에", etc.) and
# connective particles mark natural pause points.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=,)\s+|(?<=[는면서고지만니까데서야면])\s+(?=[가-힣])"
)

# Whitespace runs.
_WHITESPACE_RE = re.compile(r"\s+")

#: Maximum characters per subtitle row.
#:
#: Promoted to module-level public constant so callers (e.g. the
#: word-timed chunker in :mod:`.word_to_subtitle`) can mirror this
#: target without re-declaring a private constant.
MAX_SUBTITLE_CHARS = 25


def chunk_subtitle_text(text: str) -> list[str]:
    """Two-pass chunker matching the FE behavior.

    Returns ``[]`` for empty / whitespace-only input. Otherwise
    returns 1+ chunks, each ≤ :data:`MAX_SUBTITLE_CHARS` long.
    """
    trimmed = (text or "").strip()
    if not trimmed:
        return []
    if len(trimmed) <= MAX_SUBTITLE_CHARS:
        return [trimmed]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(trimmed) if s.strip()]
    chunks: list[str] = []

    for sentence in sentences:
        if len(sentence) <= MAX_SUBTITLE_CHARS:
            chunks.append(sentence)
            continue
        # Pass 2: clause-level split inside an oversize sentence.
        clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(sentence) if c.strip()]
        current = ""
        for clause in clauses:
            if len(clause) > MAX_SUBTITLE_CHARS:
                # Pass 3: eojeol greedy pack — fall through when a
                # single clause is still too long.
                if current:
                    chunks.append(current)
                    current = ""
                eojeols = clause.split()
                buf = ""
                for e in eojeols:
                    nxt = f"{buf} {e}" if buf else e
                    if len(nxt) > MAX_SUBTITLE_CHARS:
                        if buf:
                            chunks.append(buf)
                        buf = e
                    else:
                        buf = nxt
                if buf:
                    current = buf
                continue
            candidate = f"{current} {clause}" if current else clause
            if len(candidate) <= MAX_SUBTITLE_CHARS:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = clause
        if current:
            chunks.append(current)

    return chunks if chunks else [trimmed[:MAX_SUBTITLE_CHARS]]


def merge_chunks_to_count(chunks: list[str], target_count: int) -> list[str]:
    """Greedy merge adjacent chunks until ``len(chunks) == target_count``.

    Used when uniform timing distribution would compress per-chunk
    duration below the readable minimum. Merging neighbors preserves
    the chunker's reading-rhythm choices better than dropping every
    other chunk.
    """
    if target_count <= 0 or not chunks:
        return chunks
    merged = list(chunks)
    while len(merged) > target_count:
        # Find the shortest adjacent pair (sum of lengths) and merge.
        best_i = 0
        best_len = len(merged[0]) + len(merged[1]) if len(merged) >= 2 else 0
        for i in range(1, len(merged) - 1):
            pair_len = len(merged[i]) + len(merged[i + 1])
            if pair_len < best_len:
                best_len = pair_len
                best_i = i
        merged[best_i] = f"{merged[best_i]} {merged[best_i + 1]}"
        del merged[best_i + 1]
    return merged
