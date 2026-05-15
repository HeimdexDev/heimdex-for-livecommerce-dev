"""Post-generation safety checks for caption responses.

Purely defensive: even though the prompt forbids person descriptions,
we verify the output before it reaches the database. Any violation is
terminal for that scene.

Korean substring matching is case-insensitive and word-boundary-unaware
by design — Korean lacks whitespace boundaries between syllables, and
partial matches (e.g. "쇼호스트님") should still trip the filter.

English matching uses simple word-boundary heuristics to avoid false
positives like "handmade" tripping on "hand".
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .base import PersonSafetyViolation


_ENGLISH_WORD_RE_CACHE: dict[tuple[str, ...], re.Pattern[str]] = {}


def _compile_english_pattern(terms: Iterable[str]) -> re.Pattern[str]:
    ascii_terms = tuple(sorted({t.lower() for t in terms if t.isascii()}))
    cached = _ENGLISH_WORD_RE_CACHE.get(ascii_terms)
    if cached is not None:
        return cached
    if not ascii_terms:
        pattern = re.compile(r"(?!x)x")  # never matches
    else:
        alternation = "|".join(re.escape(t) for t in ascii_terms)
        pattern = re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)
    _ENGLISH_WORD_RE_CACHE[ascii_terms] = pattern
    return pattern


def find_banned_terms(caption: str, banned_terms: Iterable[str]) -> list[str]:
    """Return the list of banned terms that appear in ``caption``.

    Empty list means the caption is clean.
    """

    if not caption:
        return []

    terms = list(banned_terms)
    lowered = caption.lower()

    hits: list[str] = []
    korean_terms = [t for t in terms if not t.isascii()]
    for term in korean_terms:
        if term and term.lower() in lowered:
            hits.append(term)

    english_pattern = _compile_english_pattern(terms)
    for match in english_pattern.finditer(caption):
        hits.append(match.group(0).lower())

    # Preserve input order, dedupe
    seen: set[str] = set()
    unique_hits: list[str] = []
    for hit in hits:
        key = hit.lower()
        if key not in seen:
            seen.add(key)
            unique_hits.append(hit)
    return unique_hits


def assert_person_safety(
    caption: str,
    has_person: bool,
    banned_terms: Iterable[str],
) -> None:
    """Raise PersonSafetyViolation if the caption leaks banned terms.

    The rule is intentionally asymmetric:
      - has_person == True  → caption MUST contain no banned terms
      - has_person == False → same check, defense in depth against the
        model denying a person is visible while describing them anyway.

    In other words, banned terms are banned *regardless* of the flag.
    The flag exists for the downstream pipeline, not for the safety check.
    """

    hits = find_banned_terms(caption, banned_terms)
    if hits:
        raise PersonSafetyViolation(
            f"caption contains banned person terms: {hits!r} "
            f"(has_person={has_person})"
        )
