"""Pure-function scene scorer. Wraps the contracts-side scorer.

This is the default implementation and the fallback target for the LLM
scorer. Keep it synchronous-underneath + async-shaped so both scorers
present the same interface to the service.
"""

from __future__ import annotations

from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.concatenator import ScoredScene
from heimdex_media_contracts.shorts.scorer import score_scene_for_mode

from .base import SceneScorer, ScoringContext


class PureSceneScorer(SceneScorer):
    name = "pure"

    async def score(
        self,
        scenes: list[SceneDocument],
        context: ScoringContext,
    ) -> list[ScoredScene]:
        return [
            ScoredScene(
                scene=scene,
                breakdown=score_scene_for_mode(
                    scene,
                    context.mode,
                    person_cluster_id=context.person_cluster_id,
                ),
            )
            for scene in scenes
        ]
