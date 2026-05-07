"""Storyboard picker contract.

Defines the surface that ``service.py`` calls into and that BOTH
the heuristic (Tier B, this PR) and LLM-director (Tier C, future)
implementations satisfy. Keeping the protocol narrow lets us swap
the implementation behind the
``auto_shorts_product_v2_storyboard_picker`` setting without
touching the orchestrator.

Why a Protocol (structural typing) rather than ABC: implementations
in Tier C live in a separate module that may carry heavy deps
(``openai`` client, prompt template) — Protocol lets us mock them
in unit tests with ``unittest.mock.MagicMock(spec=StoryboardPicker)``
without forcing inheritance.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.shorts_auto_product.track_stt.models import (
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    StoryboardPlan,
)


class StoryboardPicker(Protocol):
    """Picks role-labelled fragments from already-scored chunks.

    Contract:
        * Pure with respect to ``ScoredChunk[]`` for Tier B; Tier C
          adds an LLM call but the Protocol stays the same.
        * MUST NOT raise on edge cases (empty chunks, no CTA found,
          single-segment input). Return an empty ``StoryboardPlan``
          OR a degraded plan with ``fallbacks_used`` populated. The
          orchestrator then decides whether to fall back to the
          legacy ``clip_selector.select_top_chunks`` path.
        * Returned fragments MUST NOT overlap in source-time. A chunk
          that fills HOOK is excluded from INTRO/DETAIL/CTA candidate
          sets — the Protocol doesn't enforce this, but tests do.
        * ``total_duration_ms`` ≤ ``target_duration_ms`` after
          per-slot clamping. The composition_builder still applies
          its own scene-boundary clamps on top, so this is an upper
          bound, not an exact match.
    """

    async def assemble(
        self,
        *,
        all_chunks: list[ScoredChunk],
        segments: list[MentionSegment],
        target_duration_ms: int,
        llm_label: str,
        spoken_aliases: list[str],
        org_id: UUID | None = None,
    ) -> StoryboardPlan:
        """Build the storyboard plan. See module docstring for the
        contract details. ``org_id`` is forwarded for Tier C's LLM
        cost tracking; Tier B ignores it.
        """
        ...
