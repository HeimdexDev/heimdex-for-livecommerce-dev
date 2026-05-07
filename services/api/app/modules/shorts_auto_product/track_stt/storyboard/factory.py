"""Storyboard picker factory.

Maps the ``auto_shorts_product_v2_storyboard_*`` settings to a
concrete ``StoryboardPicker`` implementation. Lives in the
``storyboard/`` submodule so the picker contract and its
implementations stay co-located; the orchestrator
(``track_stt/service.py``) imports only this factory.

Future Tier C ``LlmStoryboardPicker`` adds a new branch here when
it lands. Currently raises ``NotImplementedError`` for
``picker="llm"`` so a misconfigured staging environment surfaces
loudly rather than silently falling back to heuristic.
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.shorts_auto_product.track_stt.storyboard.heuristic_picker import (
    HeuristicStoryboardPicker,
)
from app.modules.shorts_auto_product.track_stt.storyboard.picker_protocol import (
    StoryboardPicker,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    SlotBudgets,
)

logger = logging.getLogger(__name__)


def build_storyboard_picker_from_settings(
    settings: Any,
) -> StoryboardPicker | None:
    """Return a concrete ``StoryboardPicker`` based on settings.

    Returns ``None`` when storyboard mode is disabled — callers then
    fall back to the legacy ``clip_selector`` path.

    Pure: reads settings only at call time so test fixtures can
    override per-test without mutating module state.
    """
    if not getattr(
        settings,
        "auto_shorts_product_v2_storyboard_mode_enabled",
        False,
    ):
        return None

    picker_type = getattr(
        settings,
        "auto_shorts_product_v2_storyboard_picker",
        "heuristic",
    )

    budgets = SlotBudgets(
        hook_ms=getattr(
            settings, "auto_shorts_product_v2_storyboard_hook_ms", 8_000,
        ),
        intro_ms=getattr(
            settings, "auto_shorts_product_v2_storyboard_intro_ms", 12_000,
        ),
        detail_ms=getattr(
            settings, "auto_shorts_product_v2_storyboard_detail_ms", 25_000,
        ),
        cta_ms=getattr(
            settings, "auto_shorts_product_v2_storyboard_cta_ms", 8_000,
        ),
    )

    if picker_type == "heuristic":
        logger.debug(
            "stt_storyboard_picker_built",
            extra={"picker": "heuristic", "budgets": budgets.__dict__},
        )
        return HeuristicStoryboardPicker(budgets=budgets)

    if picker_type == "llm":
        # Tier C placeholder — when ``LlmStoryboardPicker`` lands,
        # construct it here with ``openai_client`` + ``model`` from
        # settings. Loud failure beats silent fallback to heuristic
        # because operators flipping the switch deserve to know
        # their config didn't take effect.
        raise NotImplementedError(
            "LlmStoryboardPicker (Tier C) is not yet implemented; "
            "set auto_shorts_product_v2_storyboard_picker='heuristic' "
            "or disable storyboard mode entirely."
        )

    raise ValueError(
        f"unknown auto_shorts_product_v2_storyboard_picker={picker_type!r}; "
        f"expected 'heuristic' or 'llm'"
    )
