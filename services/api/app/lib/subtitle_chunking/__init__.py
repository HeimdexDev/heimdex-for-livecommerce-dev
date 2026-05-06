"""Pure-function subtitle chunking primitives.

Two complementary chunkers:

* :func:`chunk_subtitle_text` — character-aware chunker for plain
  transcript text. Korean-aware (sentence + clause boundaries with
  greedy eojeol fallback). Extracted from the auto-shorts product-mode
  ``track_stt/subtitle_generator.py`` so any caller (auto-shorts,
  premiere export, blur, future product-track) can reuse it.

* :func:`chunk_words` — word-timed chunker for Whisper output. Groups
  :class:`~app.lib.whisper_transcribe.WhisperWord` tokens into
  :class:`Subtitle` chunks at character-limit, silence-gap, or
  sentence-end boundaries. Validates against overlap and sub-300ms
  durations.

Loose-coupling rules
--------------------
* Zero ``app.modules.*`` imports.
* Zero I/O. All inputs are plain Python types or
  :class:`~app.lib.whisper_transcribe.WhisperWord` (which is itself
  pure data).
* Output is generic — :class:`Subtitle` is a plain dataclass, NOT
  ``heimdex_media_contracts.composition.SubtitleSpec``. Callers wrap
  the dataclass in their feature's contract type so this module
  doesn't pin to any single contracts version.
"""

from __future__ import annotations

from app.lib.subtitle_chunking.chunker import (
    MAX_SUBTITLE_CHARS,
    chunk_subtitle_text,
    merge_chunks_to_count,
)
from app.lib.subtitle_chunking.word_to_subtitle import Subtitle, chunk_words

__all__ = [
    "MAX_SUBTITLE_CHARS",
    "Subtitle",
    "chunk_subtitle_text",
    "chunk_words",
    "merge_chunks_to_count",
]
