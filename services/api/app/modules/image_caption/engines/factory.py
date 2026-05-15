"""Engine factory for the image caption path inside the api container.

Unlike the earlier queue_kind-dispatched version (which also handled video
via a legacy adapter), the api path only ever needs the OpenAI image
engine. Dropping the legacy branch means:
  - No import of heimdex_media_pipelines.vision (not in the api container)
  - No conditional branching at call time
  - One engine, one code path

If we later need to support additional image-captioning backends (Gemini,
Claude), add an `image_caption_engine` enum field to Settings and branch
here. For phase 1 we're committed to OpenAI gpt-4o only.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import CaptionEngine

logger = logging.getLogger(__name__)


def build_image_caption_engine(settings: Any) -> CaptionEngine:
    """Construct the OpenAI caption engine from api Settings.

    Caller is responsible for checking settings.image_caption_enabled
    before invoking this. We raise rather than returning a no-op engine
    so misconfiguration fails loudly at startup.
    """

    from .openai_client import InMemoryBudgetTracker, OpenAICaptionClient
    from .openai_engine import OpenAICaptionEngine
    from .openai_prompt import PROMPT_VERSION

    api_key = getattr(settings, "openai_api_key", "") or ""
    if not api_key:
        raise RuntimeError(
            "openai_api_key is empty; cannot build image caption engine. "
            "Set OPENAI_API_KEY in the api container environment."
        )

    model = getattr(settings, "image_caption_model", "gpt-4o")
    image_detail = getattr(settings, "image_caption_image_detail", "low")
    timeout_s = float(getattr(settings, "image_caption_timeout_s", 30.0))
    max_concurrency = int(getattr(settings, "image_caption_max_concurrency", 4))
    daily_budget_usd = float(getattr(settings, "image_caption_daily_budget_usd", 50.0))
    estimated_cost_per_call_usd = float(
        getattr(settings, "image_caption_estimated_cost_per_call_usd", 0.012)
    )

    budget_tracker = InMemoryBudgetTracker(daily_budget_usd=daily_budget_usd)

    client = OpenAICaptionClient(
        api_key=api_key,
        model=model,
        timeout_s=timeout_s,
        max_concurrency=max_concurrency,
        budget_tracker=budget_tracker,
        estimated_cost_per_call_usd=estimated_cost_per_call_usd,
    )

    prompt_version = getattr(
        settings, "image_caption_prompt_version", PROMPT_VERSION
    )

    logger.info(
        "image_caption_engine_loaded",
        extra={
            "model": model,
            "image_detail": image_detail,
            "max_concurrency": max_concurrency,
            "daily_budget_usd": daily_budget_usd,
            "prompt_version": prompt_version,
        },
    )

    return OpenAICaptionEngine(
        client=client,
        image_detail=image_detail,
        prompt_version=prompt_version,
    )
