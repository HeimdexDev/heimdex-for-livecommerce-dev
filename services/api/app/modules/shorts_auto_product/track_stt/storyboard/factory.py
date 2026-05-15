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
        # Tier C — LLM director. Plan:
        # ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md``.
        #
        # Lazy-import the OpenAI SDK + LlmStoryboardPicker so the
        # heuristic-mode startup path doesn't pay for the SDK
        # construction cost. Mirrors the
        # ``whisper_transcribe._get_transcriber`` lazy-singleton
        # pattern.
        from openai import AsyncOpenAI  # type: ignore[import-not-found]

        from app.lib.whisper_transcribe.budget import (
            InMemoryBudgetTracker as _InMemoryBudgetTracker,
        )
        from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
            LlmStoryboardPicker,
        )

        api_key = (getattr(settings, "openai_api_key", "") or "").strip()
        if not api_key:
            # Soft fallback: deploy missing OPENAI_API_KEY shouldn't
            # crash the storyboard pipeline. Log loud so the operator
            # sees the misconfig in the next deploy log scrape.
            logger.warning(
                "stt_storyboard_llm_disabled_no_api_key — "
                "falling back to heuristic picker; set OPENAI_API_KEY "
                "or AUTO_SHORTS_PRODUCT_V2_STORYBOARD_PICKER=heuristic "
                "to silence this warning",
                extra={"picker_requested": "llm"},
            )
            return HeuristicStoryboardPicker(budgets=budgets)

        model = getattr(
            settings, "auto_shorts_product_v2_storyboard_llm_model",
            "gpt-4o-mini",
        )
        timeout_s = float(getattr(
            settings, "auto_shorts_product_v2_storyboard_llm_timeout_s",
            5.0,
        ))
        daily_budget_usd = float(getattr(
            settings,
            "auto_shorts_product_v2_storyboard_llm_daily_budget_usd",
            5.0,
        ))
        prompt_version = getattr(
            settings,
            "auto_shorts_product_v2_storyboard_llm_prompt_version",
            "v1",
        )
        cta_min_position = float(getattr(
            settings,
            "auto_shorts_product_v2_storyboard_cta_min_position",
            0.5,
        ))
        logger.debug(
            "stt_storyboard_picker_built",
            extra={
                "picker": "llm",
                "model": model,
                "timeout_s": timeout_s,
                "daily_budget_usd": daily_budget_usd,
                "prompt_version": prompt_version,
                "cta_min_position": cta_min_position,
                "budgets": budgets.__dict__,
            },
        )
        return LlmStoryboardPicker(
            openai_client=AsyncOpenAI(api_key=api_key),
            model=model,
            prompt_version=prompt_version,
            timeout_s=timeout_s,
            budgets=budgets,
            budget_tracker=_InMemoryBudgetTracker(
                daily_budget_usd=daily_budget_usd,
            ),
            fallback=HeuristicStoryboardPicker(budgets=budgets),
            cta_min_position=cta_min_position,
        )

    raise ValueError(
        f"unknown auto_shorts_product_v2_storyboard_picker={picker_type!r}; "
        f"expected 'heuristic' or 'llm'"
    )
