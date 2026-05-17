"""Speech Segments pipeline — re-exported from heimdex-media-pipelines.

The pipeline logic is defined in ``heimdex_media_pipelines.speech.pipeline``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_pipelines.speech.pipeline import (  # noqa: F401
    SpeechSegmentsPipeline,
)

__all__ = [
    "SpeechSegmentsPipeline",
]