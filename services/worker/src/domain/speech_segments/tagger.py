"""Speech tagger — re-exported from heimdex-media-contracts.

The tagger logic is defined in ``heimdex_media_contracts.speech.tagger``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_contracts.speech.tagger import (  # noqa: F401
    DEFAULT_KEYWORD_DICT,
    SpeechTagger,
)

__all__ = [
    "DEFAULT_KEYWORD_DICT",
    "SpeechTagger",
]