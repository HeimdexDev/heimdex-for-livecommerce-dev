"""OpenAI Whisper async transcription wrapper.

Word-level timestamps for clip-sized audio (≤25 MB upload limit). Used by
the auto-shorts post-render hook to refine subtitles after the initial
render lands. Pure I/O wrapper — no business logic about WHEN to
transcribe lives here; that belongs to the caller.

Loose-coupling rules
--------------------
* Zero ``app.modules.*`` imports. This module is reusable across
  shorts-render, premiere export, blur, and the v3 product-track worker
  if any of them want timed subtitles later.
* The budget tracker is currently duplicated from
  ``app/modules/shorts_auto/llm/budget.py`` and
  ``app/modules/image_caption/engines/openai_client.py`` (third copy as
  of 2026-05-06). The note in ``shorts_auto/llm/budget.py:5-6`` says
  "promote to a shared ``app/lib/openai/`` module only once a second
  feature uses it" — that promotion is now overdue. Tracked as a
  follow-up; PR 1 keeps the duplication to stay additive.

Public surface
--------------
* :class:`WhisperWord` — single word with millisecond bounds.
* :class:`WhisperResult` — the full transcript + cost + latency.
* :class:`WhisperTranscriber` — async client; one instance per process.
* :class:`InMemoryBudgetTracker` — daily-USD ceiling, UTC reset.
* :class:`BudgetExceededError` — raised pre-call when ceiling hit.
* :class:`WhisperTerminalError` — 4xx; do not retry.
* :class:`WhisperRetryableError` — 429/5xx after retries exhausted.
"""

from __future__ import annotations

from app.lib.whisper_transcribe.budget import (
    BudgetExceededError,
    BudgetTracker,
    InMemoryBudgetTracker,
)
from app.lib.whisper_transcribe.client import (
    WhisperRetryableError,
    WhisperTerminalError,
    WhisperTranscriber,
)
from app.lib.whisper_transcribe.schemas import WhisperResult, WhisperWord

__all__ = [
    "BudgetExceededError",
    "BudgetTracker",
    "InMemoryBudgetTracker",
    "WhisperResult",
    "WhisperRetryableError",
    "WhisperTerminalError",
    "WhisperTranscriber",
    "WhisperWord",
]
