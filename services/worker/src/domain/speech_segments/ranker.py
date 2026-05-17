"""Segment ranker — re-exported from heimdex-media-contracts.

The ranker logic is defined in ``heimdex_media_contracts.speech.ranker``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_contracts.speech.ranker import SegmentRanker  # noqa: F401

__all__ = [
    "SegmentRanker",
]