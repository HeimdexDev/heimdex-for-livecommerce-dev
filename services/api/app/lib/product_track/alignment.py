# VENDORED from heimdex-media-pipelines v0.12.3 (5d82c7d).
# See app/lib/product_track/__init__.py for the sync ritual.
"""Narration + OCR alignment annotation.

Given the assembled appearance windows + the catalog entry's
``llm_label``, mark each window with two booleans the subset picker
uses for scoring:

* ``has_narration_mention`` — any token of the label appears as a
  substring in any transcript segment that overlaps the window's
  ``[start_ms, end_ms]``.
* ``has_ocr_overlap`` — any OCR text overlaps the window. Plan §6.2
  step 5 keeps this loose for v1 (boolean, no per-token match).

Pure function: workers pre-fetch transcripts + OCR for the relevant
scenes from the api's internal endpoints and pass them in.

Korean handling notes (plan §6.2 step 5):
  * substring match works for Hangul without tokenization.
  * Romanization fallback for English-labeled products in Korean
    transcripts (e.g., "Cetaphil" → "세타필") is a v2 enhancement.
    For v1 we accept the false-negative rate; the subset picker
    composite score doesn't hard-gate on narration so a missed
    mention only loses the narration weight share.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.lib.product_track.window_assembly import (
    AssembledWindow,
)


@dataclass(frozen=True)
class TranscriptSegment:
    """Per-scene transcript segment from the api's internal scene
    endpoint. Multiple segments per scene are common (one per ASR
    utterance / diarized turn).
    """

    scene_id: str
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class OcrSegment:
    """One OCR detection from a keyframe in the scene. Workers pull
    these per-scene; per-keyframe granularity is collapsed to
    per-scene for v1 since OCR doesn't provide reliable temporal
    bounds.
    """

    scene_id: str
    text: str
    # Optional temporal bounds — when None, the segment is treated as
    # spanning the entire scene (which is the common v1 case).
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True)
class AnnotatedWindow(AssembledWindow):
    """An assembled window enriched with alignment booleans. Inherits
    every field from AssembledWindow so downstream modules can treat
    it as a drop-in replacement."""

    has_narration_mention: bool = False
    has_ocr_overlap: bool = False


# Tokens shorter than this are stripped from the label — single-char
# Korean particles or English articles produce too many false
# positives in the substring search.
_MIN_LABEL_TOKEN_LEN = 2


def annotate_alignment(
    windows: list[AssembledWindow],
    *,
    label: str,
    transcripts: dict[str, list[TranscriptSegment]] | None = None,
    ocr: dict[str, list[OcrSegment]] | None = None,
) -> list[AnnotatedWindow]:
    """Return ``windows`` with ``has_narration_mention`` /
    ``has_ocr_overlap`` populated.

    ``transcripts`` and ``ocr`` are scene_id → list maps. Missing
    scenes (no transcript or no OCR yet) yield ``False`` for that
    boolean — the subset picker composite score handles that
    gracefully.

    Rejected windows are passed through unchanged but still get the
    booleans populated so callers can persist them for tuning.
    """
    transcripts = transcripts or {}
    ocr = ocr or {}
    label_tokens = _label_tokens(label)

    out: list[AnnotatedWindow] = []
    for w in windows:
        scene_segments = transcripts.get(w.scene_id, [])
        scene_ocr = ocr.get(w.scene_id, [])

        narration = _has_narration_mention(
            scene_segments,
            label_tokens,
            window_start_ms=w.window_start_ms,
            window_end_ms=w.window_end_ms,
        )
        ocr_overlap = _has_ocr_overlap(
            scene_ocr,
            window_start_ms=w.window_start_ms,
            window_end_ms=w.window_end_ms,
        )

        out.append(
            AnnotatedWindow(
                scene_id=w.scene_id,
                window_start_ms=w.window_start_ms,
                window_end_ms=w.window_end_ms,
                avg_bbox_area_pct=w.avg_bbox_area_pct,
                avg_confidence=w.avg_confidence,
                peak_confidence=w.peak_confidence,
                frame_count=w.frame_count,
                rejected_reason=w.rejected_reason,
                has_narration_mention=narration,
                has_ocr_overlap=ocr_overlap,
            )
        )
    return out


def _label_tokens(label: str) -> list[str]:
    """Split the label into matchable substring tokens. Whitespace +
    common punctuation are separators. Tokens shorter than
    ``_MIN_LABEL_TOKEN_LEN`` are dropped to limit substring false
    positives."""

    if not label:
        return []
    parts = re.split(r"[\s,/()|+&\-]+", label.strip().lower())
    return [p for p in parts if len(p) >= _MIN_LABEL_TOKEN_LEN]


def _has_narration_mention(
    segments: list[TranscriptSegment],
    label_tokens: list[str],
    *,
    window_start_ms: int,
    window_end_ms: int,
) -> bool:
    if not label_tokens:
        return False
    for seg in segments:
        if not _intervals_overlap(
            seg.start_ms, seg.end_ms, window_start_ms, window_end_ms
        ):
            continue
        text_lc = seg.text.lower()
        if any(tok in text_lc for tok in label_tokens):
            return True
    return False


def _has_ocr_overlap(
    segments: list[OcrSegment],
    *,
    window_start_ms: int,
    window_end_ms: int,
) -> bool:
    """Return True iff any OCR segment overlaps the window AND has
    non-empty text. Segments without temporal bounds are assumed to
    span the whole scene → treated as overlapping any window in that
    scene."""

    for seg in segments:
        if not seg.text.strip():
            continue
        if seg.start_ms is None or seg.end_ms is None:
            return True
        if _intervals_overlap(
            seg.start_ms, seg.end_ms, window_start_ms, window_end_ms
        ):
            return True
    return False


def _intervals_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end
