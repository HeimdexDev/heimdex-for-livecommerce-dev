"""Typed errors for the STT-first enumeration pipeline.

Three failure shapes the orchestrator branches on:

* :class:`TranscriptUnavailableError` — the video has no searchable
  transcript (STT/VLM enrichment hasn't run yet, or every scene's
  ``transcript_raw`` is empty). The orchestrator logs an info-level
  ``no_transcript_available`` and short-circuits to zero products;
  the parallel vision path still runs and the wizard surfaces
  whatever vision finds.

* :class:`EnumerationLLMError` — the gpt-4o-mini call timed out,
  returned malformed JSON, or hit the OpenAI rate limit. The
  orchestrator logs at warning, increments the failure counter, and
  short-circuits to zero products. The vision path is unaffected.

* :class:`STTEnumerationError` (base) — anything else.

Distinct from :mod:`shorts_auto_product.track_stt.errors` which
covers the SECOND-stage STT pipeline (mention extraction → clip
assembly per a chosen catalog entry). Same naming convention but
different lifecycle.
"""

from __future__ import annotations


class STTEnumerationError(Exception):
    """Base for STT-first enumeration failures the orchestrator handles."""


class TranscriptUnavailableError(STTEnumerationError):
    """No scene in the video has non-empty ``transcript_raw``.

    This is NOT a hard failure — the parallel vision path still runs
    and the wizard renders whatever vision finds. The orchestrator
    logs ``info`` (not ``warning``) because some videos genuinely
    have no spoken content (silent product demos, slideshow-style
    livecommerce) and that's expected.
    """


class EnumerationLLMError(STTEnumerationError):
    """The transcript LLM call failed — timeout, schema mismatch,
    OpenAI rate limit, content filter.

    The orchestrator catches this and short-circuits to zero
    STT-source products. The vision path is unaffected. Repeated
    failures across multiple scans should page on the existing
    OpenAI cost / error rate dashboard (same Slack alert as
    auto_shorts_llm).
    """
