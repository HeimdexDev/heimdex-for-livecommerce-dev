"""Storyboard data shapes — internal dataclasses for the picker
contract.

Plain frozen dataclasses (NOT pydantic) because these never cross a
network boundary; they live entirely inside the api process between
the picker and ``composition_builder``. Mirrors the
``track_stt/models.py`` convention.

Two consumers:
    * ``HeuristicStoryboardPicker`` (Tier B, this PR) returns a
      ``StoryboardPlan``.
    * ``LlmStoryboardPicker`` (Tier C, future) will return the same
      shape with LLM-derived rationales.

The plan is then handed to ``composition_builder.build_composition_spec``
which converts each ``StoryboardFragment`` into one or more
``SceneClipSpec`` entries (split across scene boundaries as needed,
mirroring the existing chunk-splitting logic).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.modules.shorts_auto_product.track_stt.models import ChunkScore


class SlotRole(str, Enum):
    """The narrative role a fragment plays in the final clip.

    Order corresponds to canonical storyboard order in the rendered
    output: HOOK opens, CTA closes. The picker may select fragments
    from non-contiguous source-time ranges; the renderer concatenates
    them in this order.
    """

    HOOK = "hook"        # 5-10s — opening attention grab
    INTRO = "intro"      # 8-15s — names/contextualises the product
    DETAIL = "detail"    # 15-25s — demo/explanation/value
    CTA = "cta"          # 5-10s — purchase prompt or closer


# Stable order for sorting fragments into storyboard order. The
# picker always emits fragments with these roles; service.py uses
# this map to sort before handing to composition_builder.
SLOT_ORDER: dict[SlotRole, int] = {
    SlotRole.HOOK: 0,
    SlotRole.INTRO: 1,
    SlotRole.DETAIL: 2,
    SlotRole.CTA: 3,
}


@dataclass(frozen=True)
class SlotBudgets:
    """Slot-by-slot duration budgets in milliseconds.

    Defaults sum to 53s, leaving ~7s headroom for a 60s target —
    fragments may come in shorter when the underlying chunk is
    smaller than the budget, so the headroom prevents target
    overshoot. Tunable via env (``auto_shorts_product_v2_storyboard_*_ms``)
    so we can iterate on staging without redeploying.
    """

    hook_ms: int = 8_000
    intro_ms: int = 12_000
    detail_ms: int = 25_000
    cta_ms: int = 8_000

    def for_role(self, role: SlotRole) -> int:
        """Lookup the budget for a given slot role."""
        return {
            SlotRole.HOOK: self.hook_ms,
            SlotRole.INTRO: self.intro_ms,
            SlotRole.DETAIL: self.detail_ms,
            SlotRole.CTA: self.cta_ms,
        }[role]


@dataclass(frozen=True)
class StoryboardFragment:
    """One chunk-derived piece of the final clip.

    ``source_start_ms`` and ``source_end_ms`` reference the SOURCE
    video timeline (NOT the rendered timeline). The composition
    builder is responsible for clamping these to underlying scene
    boundaries and accumulating ``timeline_start_ms`` for each
    emitted ``SceneClipSpec``.
    """

    role: SlotRole
    source_start_ms: int
    source_end_ms: int
    # The slot budget the picker allocated to this fragment. May
    # exceed ``source_end_ms - source_start_ms`` when the underlying
    # chunk is shorter than the slot budget — composition_builder
    # uses the actual range, ``target_duration_ms`` is for telemetry.
    target_duration_ms: int
    # Carried per-chunk score for telemetry — lets us spot-check
    # picker decisions without re-running the LLM.
    chunk_score: ChunkScore
    # Free-form debug string explaining WHY this chunk filled this
    # slot (e.g., ``"max_hook_score=0.91"`` or, in Tier C, the LLM's
    # rationale). Surfaced via ``?debug=storyboard`` operator UI.
    rationale: str = ""

    @property
    def actual_duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


@dataclass(frozen=True)
class StoryboardPlan:
    """Picker output. Service.py hands this to composition_builder.

    ``fragments`` are in storyboard order (HOOK → INTRO → DETAIL →
    CTA). The DETAIL slot may contribute multiple fragments (sorted
    chronologically among themselves) when the picker breaks DETAIL
    into 2 sub-fragments to span more of the source video.

    ``slots_filled`` is a quick lookup for telemetry; ``fallbacks_used``
    captures every degraded path the picker took (e.g., no explicit
    CTA → fall back to high-hook chunk near end). Both surfaced as
    log fields.
    """

    fragments: list[StoryboardFragment]
    total_duration_ms: int
    slots_filled: set[SlotRole] = field(default_factory=set)
    fallbacks_used: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.fragments
