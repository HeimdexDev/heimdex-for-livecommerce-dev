"""Typed errors for the STT pipeline.

Three failure shapes the orchestrator branches on:

* :class:`NoMentionsFoundError` — BM25 + (optional fallbacks) returned
  zero scenes. The wizard should surface a friendly Korean message
  ("선택하신 상품에 대한 발화나 시각적 단서가 영상에서 충분히
  발견되지 않았습니다") rather than render an irrelevant clip.
* :class:`TranscriptUnavailableError` — the video has zero scenes
  with non-empty ``transcript_raw`` AND zero with non-empty
  ``scene_caption``. Different from "no mentions" — there's nothing
  to search at all (e.g., STT pipeline failed and VLM caption pass
  also empty). UI message suggests "wait for enrichment".
* :class:`SttPipelineError` (base) — anything else (OS unreachable,
  budget exhausted mid-batch, unexpected exception). Caller writes
  ``error_code='internal_error'`` and lets the wizard's
  ``friendlyParentError`` mapper turn it into the generic
  retry-please message.

:class:`MentionExtractionError` is the OS-side specialization — used
internally by ``mention_extractor`` to distinguish "OS query failed"
from "OS query returned zero hits" so the orchestrator can decide
between a retry-able failure and a clean ``NoMentionsFoundError``.
"""

from __future__ import annotations


class SttPipelineError(Exception):
    """Base for STT-pipeline failures the orchestrator handles."""


class NoMentionsFoundError(SttPipelineError):
    """BM25 (and any fallbacks) returned zero qualifying scenes for
    this catalog entry. NOT an internal error — the wizard surfaces
    a friendly Korean message and the user picks a different product.
    """


class TranscriptUnavailableError(SttPipelineError):
    """The video itself has no searchable text — neither
    ``transcript_raw`` nor ``scene_caption`` are populated on any
    scene. The user should wait for STT/VLM enrichment to complete
    before re-trying.
    """


class MentionExtractionError(SttPipelineError):
    """OS query failed (transport error, malformed query, etc.). The
    orchestrator treats this as retryable; ``NoMentionsFoundError``
    is the explicit zero-hits signal.
    """


class LiveBlockTooShortError(SttPipelineError):
    """The video's combined live-block duration is shorter than the
    requested target clip length. The Phase 1 live-only filter is on
    and the host commentary segment is too brief to source a clip
    from.

    NOT an internal error — the wizard should surface a Korean
    message like "이 영상의 호스트 발화 구간(Xs)이 요청하신 쇼츠
    길이(Ys)보다 짧아 영상을 만들 수 없습니다." so the user picks
    a different length or a different source video.
    """
