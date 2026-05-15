"""Immutable data shapes for Whisper transcription results.

Frozen dataclasses + ``tuple`` containers — callers can pass these
across module boundaries without worrying about mutation. Conversion
to ``SubtitleSpec`` (auto-shorts style) happens in the caller, not
here, to keep this module decoupled from contract-package versions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WhisperWord:
    """A single word with millisecond-precision bounds.

    OpenAI's Whisper API returns word timestamps as floating-point
    seconds. We convert to integer milliseconds at parse time so
    downstream code (subtitle chunker, composition builder) can use
    integer math throughout — matches the rest of the codebase's
    timeline-arithmetic convention.

    Invariants (enforced at construction by ``__post_init__``):
        - ``start_ms >= 0``
        - ``end_ms >= start_ms``
        - ``word`` is non-empty after strip()
    """

    word: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if not self.word or not self.word.strip():
            raise ValueError("WhisperWord.word must be non-empty")
        if self.start_ms < 0:
            raise ValueError(
                f"WhisperWord.start_ms must be >= 0, got {self.start_ms}"
            )
        if self.end_ms < self.start_ms:
            raise ValueError(
                f"WhisperWord.end_ms ({self.end_ms}) must be >= "
                f"start_ms ({self.start_ms})"
            )


@dataclass(frozen=True)
class WhisperResult:
    """Full transcript + telemetry for a single Whisper call.

    Attributes:
        words: Tuple of :class:`WhisperWord` in chronological order.
            May be empty when Whisper detects no speech (silence,
            non-speech audio, etc.). Caller must handle empty.
        text: The concatenated transcript text, as Whisper returned it.
            Useful for logging and the ``prompt`` parameter on
            subsequent calls (term-biasing).
        language: ISO 639-1 code Whisper detected or was pinned to
            (e.g. ``"ko"``).
        duration_seconds: Audio duration as Whisper reports it. May
            differ slightly from caller-supplied estimate; use this
            for cost recording.
        cost_usd: Actual cost computed from ``duration_seconds``.
        latency_ms: Wall-clock time for the API call (excludes
            network download time before the call).
    """

    words: tuple[WhisperWord, ...]
    text: str
    language: str
    duration_seconds: float
    cost_usd: float
    latency_ms: int
