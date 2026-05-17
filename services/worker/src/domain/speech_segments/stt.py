"""STT (Speech-to-Text) — re-exported from heimdex-media-pipelines.

The STT logic is defined in ``heimdex_media_pipelines.speech.stt``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_pipelines.speech.stt import (  # noqa: F401
    STTProcessor,
    TranscriptSegment,
    convert_to_speech_segments,
)

__all__ = [
    "STTProcessor",
    "TranscriptSegment",
    "convert_to_speech_segments",
]