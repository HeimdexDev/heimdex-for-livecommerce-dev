"""Group word-timestamped Whisper output into timed subtitle chunks.

Where :func:`~app.lib.subtitle_chunking.chunker.chunk_subtitle_text`
splits plain text by character + clause heuristics, this module
splits a *time-stamped* word stream by:

* character limit (same target as the text chunker for visual parity)
* silence gap between words (>500ms by default — natural pause)
* sentence-ending punctuation on the previous word

Outputs :class:`Subtitle` (start_ms, end_ms, text). Validation drops
sub-300ms chunks (sub-perceptual) and clamps overlap with the prior
chunk's end. Caller wraps :class:`Subtitle` in their feature's
contract type (e.g. ``heimdex_media_contracts.composition.SubtitleSpec``)
so this module stays independent of contract-package versions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.lib.subtitle_chunking.chunker import MAX_SUBTITLE_CHARS
from app.lib.whisper_transcribe.schemas import WhisperWord

# Punctuation that ends a sentence in either Korean or Latin scripts.
# Used to break early when the previous word terminates with one of
# these — keeps "안녕하세요." as the trailing word of a chunk rather
# than starting the next chunk with a fragment.
_SENTENCE_END_CHARS = ".!?。?!"


@dataclass(frozen=True)
class Subtitle:
    """A timed subtitle chunk.

    Plain dataclass — NOT ``heimdex_media_contracts.composition.SubtitleSpec``.
    Caller is responsible for adapting to the contract type of their
    feature (auto-shorts, premiere export, etc.) so this module
    doesn't pin to a contracts version.
    """

    start_ms: int
    end_ms: int
    text: str


def chunk_words(
    words: Sequence[WhisperWord],
    *,
    max_chars: int = MAX_SUBTITLE_CHARS,
    max_gap_ms: int = 500,
    min_duration_ms: int = 300,
    timeline_clamp_ms: int | None = None,
) -> list[Subtitle]:
    """Group word-timed tokens into subtitle chunks.

    Args:
        words: Whisper word stream in chronological order. Empty
            input returns an empty list.
        max_chars: Soft target for chunk length. A new chunk starts
            when adding the next word would exceed this. Default 25,
            matching the FE chunker.
        max_gap_ms: Silence threshold for forcing a chunk boundary.
            If the gap between the prior word's ``end_ms`` and the
            next word's ``start_ms`` exceeds this, start a new chunk.
            Default 500ms.
        min_duration_ms: Drop chunks shorter than this after
            validation. Sub-perceptual flicker hurts UX more than
            losing a stray fragment. Default 300ms.
        timeline_clamp_ms: Optional hard upper bound for ``end_ms``.
            Use this when the chunker output will be placed on a
            fixed-duration timeline (e.g. clip total length). Chunks
            extending past this are clamped, then dropped if clamping
            makes them sub-``min_duration_ms``.

    Returns:
        Chronological list of :class:`Subtitle`. Each subtitle's
        ``end_ms`` is strictly less than the next subtitle's
        ``start_ms`` (no overlap).

    Notes:
        - A single word longer than ``max_chars`` will still be one
          subtitle — we never split inside a word.
        - The text uses single-space joining; Whisper's word strings
          are stripped before joining to neutralize leading-space
          quirks observed in real responses.
        - Validation passes preserve chronological order; chunks are
          never reordered, only clamped or dropped.
    """
    if not words:
        return []
    if max_chars <= 0:
        raise ValueError(f"max_chars must be positive, got {max_chars}")
    if max_gap_ms < 0:
        raise ValueError(f"max_gap_ms must be >= 0, got {max_gap_ms}")
    if min_duration_ms < 0:
        raise ValueError(f"min_duration_ms must be >= 0, got {min_duration_ms}")

    raw_chunks = _group_into_chunks(
        words,
        max_chars=max_chars,
        max_gap_ms=max_gap_ms,
    )
    return _validate_and_clamp(
        raw_chunks,
        min_duration_ms=min_duration_ms,
        timeline_clamp_ms=timeline_clamp_ms,
    )


def _group_into_chunks(
    words: Sequence[WhisperWord],
    *,
    max_chars: int,
    max_gap_ms: int,
) -> list[Subtitle]:
    chunks: list[Subtitle] = []
    current: list[WhisperWord] = []
    current_text_len = 0  # tracks chunk char count including joining spaces

    for word in words:
        text = word.word.strip()
        if not text:
            continue

        if current:
            prev = current[-1]
            prev_text = prev.word.strip()
            # +1 for the joining space between words
            projected_len = current_text_len + 1 + len(text)
            gap_ms = word.start_ms - prev.end_ms
            ends_sentence = bool(prev_text) and prev_text[-1:] in _SENTENCE_END_CHARS

            if (
                projected_len > max_chars
                or gap_ms > max_gap_ms
                or ends_sentence
            ):
                chunks.append(_make_subtitle(current))
                current = []
                current_text_len = 0

        current.append(word)
        if current_text_len > 0:
            current_text_len += 1
        current_text_len += len(text)

    if current:
        chunks.append(_make_subtitle(current))
    return chunks


def _make_subtitle(words: list[WhisperWord]) -> Subtitle:
    text = " ".join(w.word.strip() for w in words if w.word.strip())
    return Subtitle(
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        text=text,
    )


def _validate_and_clamp(
    chunks: list[Subtitle],
    *,
    min_duration_ms: int,
    timeline_clamp_ms: int | None,
) -> list[Subtitle]:
    out: list[Subtitle] = []
    prev_end_ms = -1
    for sub in chunks:
        start = sub.start_ms
        end = sub.end_ms

        # Forward-clamp overlap: if this chunk's start is before the
        # previous chunk's end, push it forward. This can happen when
        # Whisper emits very short gaps or near-overlapping words.
        if start < prev_end_ms:
            start = prev_end_ms
        # Clamp end to the timeline upper bound, if any.
        if timeline_clamp_ms is not None and end > timeline_clamp_ms:
            end = timeline_clamp_ms
        # Drop sub-perceptual chunks (post-clamp).
        if end - start < min_duration_ms:
            continue

        out.append(Subtitle(start_ms=start, end_ms=end, text=sub.text))
        prev_end_ms = end
    return out
