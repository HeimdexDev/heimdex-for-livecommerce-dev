"""Storyboard picker submodule — slot-based clip composition.

Tier B (heuristic) ships in 2026-05-07 — produces narratively-
ordered fragments (HOOK → INTRO → DETAIL → CTA) from already-scored
chunks. Tier C (LLM director) will replace
``HeuristicStoryboardPicker`` via the same Protocol; the rest of
the pipeline doesn't change.

Public API:
    * ``StoryboardPicker`` — Protocol that BOTH implementations
      satisfy.
    * ``HeuristicStoryboardPicker`` — Tier B picker.
    * ``StoryboardPlan`` / ``StoryboardFragment`` / ``SlotRole`` /
      ``SlotBudgets`` — output shapes consumed by composition_builder.
"""

from app.modules.shorts_auto_product.track_stt.storyboard.factory import (
    build_storyboard_picker_from_settings,
)
from app.modules.shorts_auto_product.track_stt.storyboard.heuristic_picker import (
    INTRO_IMPORTANCE_FLOOR,
    HeuristicStoryboardPicker,
)
from app.modules.shorts_auto_product.track_stt.storyboard.picker_protocol import (
    StoryboardPicker,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    SLOT_ORDER,
    SlotBudgets,
    SlotRole,
    StoryboardFragment,
    StoryboardPlan,
)

__all__ = [
    "HeuristicStoryboardPicker",
    "INTRO_IMPORTANCE_FLOOR",
    "SLOT_ORDER",
    "SlotBudgets",
    "SlotRole",
    "StoryboardFragment",
    "StoryboardPicker",
    "StoryboardPlan",
    "build_storyboard_picker_from_settings",
]
