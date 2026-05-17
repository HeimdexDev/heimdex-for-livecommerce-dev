"""Speech segment schemas — re-exported from heimdex-media-contracts.

All types are defined in ``heimdex_media_contracts.speech.schemas``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_contracts.speech.schemas import (  # noqa: F401
    PipelineResult,
    RankedSegment,
    SpeechSegment,
    TaggedSegment,
)

__all__ = [
    "SpeechSegment",
    "TaggedSegment",
    "RankedSegment",
    "PipelineResult",
]