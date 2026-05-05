"""Internal dataclasses for the STT pipeline.

Plain frozen dataclasses (NOT pydantic) because these never cross a
network boundary — they live entirely inside the api process. The
contracts library still owns the worker→API and API→worker schemas;
these are the in-process tube between modules.

Naming convention mirrors the standalone product-auto-shorts repo
(``MentionedScene``, ``MentionSegment``, ``ScoredChunk``) so anyone
who has read that repo's pipeline can read ours without re-mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID


# ---------- mention_extractor output ----------


@dataclass(frozen=True)
class MentionedScene:
    """One OS scene that BM25-matched the catalog entry's vocabulary.

    ``score`` is the OS ``_score`` value, NOT normalized — different
    queries can produce different score scales. Within a single
    pipeline run the relative ordering is what matters.
    """

    scene_id: str
    start_ms: int
    end_ms: int
    score: float

    # Which field carried the matching tokens. ``"both"`` means the
    # scene matched in transcript_raw AND scene_caption — strongest
    # signal. Used by debug telemetry, not by the assembler.
    matched_field: Literal["transcript_raw", "scene_caption", "both"]

    # Aliases that hit on this scene. Empty list when only the
    # ``llm_label`` itself matched. Surfaced to the wizard via
    # ``?debug=1`` query param (PR 4).
    matched_aliases: list[str] = field(default_factory=list)

    # Carried through for the scorer. Empty string is allowed (means
    # this scene matched via scene_caption but has no transcript).
    transcript_text: str = ""
    caption_text: str = ""


# ---------- segment_assembler output ----------


@dataclass(frozen=True)
class MentionSegment:
    """A run of consecutive mentioned scenes within ``MAX_GAP_SECONDS``
    of each other. Equivalent to standalone ``ProductSegment`` but
    without the ``product_id`` discriminator (we only handle one
    product per pipeline call — the wizard pick).
    """

    start_ms: int
    end_ms: int
    scenes: list[MentionedScene]

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


# ---------- chunk_scorer output ----------


@dataclass(frozen=True)
class ChunkScore:
    """Per-chunk scoring output, mirrors standalone ``ChunkScore``
    pydantic model field-for-field.

    All three numbers in [0.0, 1.0]. The chunk scorer's LLM contract
    enforces the bounds; the heuristic fallback also clamps.
    """

    hook_score: float
    has_cta: bool
    importance_score: float


@dataclass(frozen=True)
class ScoredChunk:
    """One ~10-30s window inside a MentionSegment with its score."""

    start_ms: int
    end_ms: int
    text: str
    score: ChunkScore

    @property
    def composite(self) -> float:
        """Single-number composite for ranking. CTA gets a small
        boost; hook gets a small boost; importance is the bulk.
        """
        boost = 0.05 if self.score.has_cta else 0.0
        return min(
            1.0,
            0.7 * self.score.importance_score
            + 0.25 * self.score.hook_score
            + boost,
        )


# ---------- service output ----------


@dataclass(frozen=True)
class SttClipResult:
    """Public return shape of ``track_stt.service.assemble_stt_clip``.

    The orchestrator persists ``render_job_id`` on the
    ``ProductScanJob`` row and surfaces it through the wizard's
    result page polling.
    """

    render_job_id: UUID
    selected_chunks: list[ScoredChunk]
    mentioned_scene_count: int
    matched_aliases: list[str]
    fallback_used: Literal["none", "coreference", "visual"] = "none"
