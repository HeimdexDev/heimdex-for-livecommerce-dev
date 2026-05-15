"""SceneScorer protocol and error hierarchy.

The service depends on this protocol; concrete scorers (pure, LLM) live
in sibling modules. Keeps the service free of imports from
``heimdex_media_contracts.shorts.scorer`` or any OpenAI client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.concatenator import ScoredScene
from heimdex_media_contracts.shorts.scorer import ScoringMode


class ScorerError(Exception):
    """Base for scorer-side failures that must trigger fallback."""


class ScorerBudgetExceededError(ScorerError):
    """Daily or per-request budget exhausted. Retry tomorrow."""


class ScorerFallbackSignal(ScorerError):
    """Raised by an LLM scorer when its output is unusable (hallucinated
    scene_ids, invalid JSON, over-duration, etc.) so the service can fall
    back to the pure scorer on the same request.
    """


@dataclass(frozen=True)
class ScoringContext:
    """Immutable inputs the scorer needs beyond the scene list.

    Passed as one object so adding a new knob (e.g. target duration for
    LLM-side duration awareness) doesn't ripple through every signature.
    """

    mode: ScoringMode
    person_cluster_id: str | None = None
    target_duration_sec: int = 60
    video_id: str = ""
    video_title: str | None = None


class SceneScorer(Protocol):
    """Scores scenes for auto-shorts clip selection.

    Implementations must be stateless per-call: two calls with the same
    inputs produce equivalent outputs. LLM scorers should use seed + temp=0
    to honor that contract.
    """

    name: str  # "pure" | "llm" — surfaced in response metadata

    async def score(
        self,
        scenes: list[SceneDocument],
        context: ScoringContext,
    ) -> list[ScoredScene]: ...
