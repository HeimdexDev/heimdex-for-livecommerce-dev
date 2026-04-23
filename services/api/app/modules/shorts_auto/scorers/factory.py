"""Factory that picks a SceneScorer based on settings + per-request rollout.

Two moving parts:
  - ``should_use_llm_for_request(settings, org_id, video_id)`` returns
    True when the master flag is on AND the request hashes into the
    current rollout bucket. Called once per request at DI time.
  - ``build_scorer(settings, use_llm=...)`` returns the scorer the
    service should invoke FIRST. The service is responsible for
    fallback-to-pure on failure — this factory only builds scorers,
    it doesn't orchestrate.

Separation here matters: the rollout decision lives at the edge (in
the router's dependency), the scorer construction is pure, and the
fallback policy lives in the service. Each can change independently.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from .base import SceneScorer
from .pure import PureSceneScorer


def should_use_llm_for_request(
    settings: Any,
    *,
    org_id: UUID,
    video_id: str,
) -> bool:
    """Return True if this request should attempt the LLM scorer.

    Gate chain:
      1. ``auto_shorts_llm_enabled`` master flag
      2. rollout_pct — (org_id|video_id) hash modulo 100 < pct
    """
    if not getattr(settings, "auto_shorts_llm_enabled", False):
        return False
    pct = int(getattr(settings, "auto_shorts_llm_rollout_pct", 0) or 0)
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    bucket = _hash_bucket(f"{org_id}|{video_id}")
    return bucket < pct


def _hash_bucket(key: str) -> int:
    """Deterministic 0-99 bucket from an arbitrary key."""
    digest = hashlib.sha1(key.encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100


def build_scorer(settings: Any, *, use_llm: bool = False) -> SceneScorer:
    """Build the primary scorer for this request.

    When ``use_llm`` is False (default), returns the pure scorer — used
    for both "LLM disabled" and "LLM fallback" code paths. When True,
    returns a fresh LLM scorer configured from settings.
    """
    if not use_llm:
        return PureSceneScorer()

    # Lazy import so the openai SDK dependency only loads when the LLM
    # scorer is actually built — keeps import-time cheap for tests.
    from ..llm.budget import InMemoryBudgetTracker
    from ..llm.client import OpenAIClipClient
    from ..llm.prompt import PROMPT_VERSION
    from .llm import OpenAILLMScorer

    api_key = getattr(settings, "openai_api_key", "") or ""
    budget = InMemoryBudgetTracker(
        daily_budget_usd=float(getattr(settings, "auto_shorts_llm_daily_budget_usd", 25.0)),
    )
    client = OpenAIClipClient(
        api_key=api_key,
        model=str(getattr(settings, "auto_shorts_llm_model", "gpt-4o-mini")),
        timeout_s=float(getattr(settings, "auto_shorts_llm_timeout_sec", 8.0)),
        budget_tracker=budget,
        estimated_cost_per_call_usd=float(
            getattr(settings, "auto_shorts_llm_estimated_cost_per_call_usd", 0.003)
        ),
    )
    return OpenAILLMScorer(
        client=client,
        max_scenes=int(getattr(settings, "auto_shorts_llm_max_scenes", 50)),
        prompt_version=str(
            getattr(settings, "auto_shorts_llm_prompt_version", PROMPT_VERSION)
        ),
    )
