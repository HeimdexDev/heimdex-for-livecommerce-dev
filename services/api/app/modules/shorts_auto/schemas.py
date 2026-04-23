"""Request/response schemas for /api/shorts/auto-* endpoints.

Mirrors the contracts-side ``ScoringMode`` enum locally so the API
surface doesn't leak the import to clients via OpenAPI. The values are
identical strings; conversion is a single ``ScoringMode(req.mode.value)``.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ScoringModeRequest(str, Enum):
    HUMAN = "human"
    PRODUCT = "product"
    BOTH = "both"


class AutoSelectRequest(BaseModel):
    video_id: str = Field(min_length=1)
    mode: ScoringModeRequest
    person_cluster_id: str | None = Field(default=None, min_length=1)
    count: int = Field(default=5, ge=1, le=10)
    target_duration_sec: int = Field(default=60, ge=15, le=180)
    min_duration_sec: int = Field(default=30, ge=5)
    prefer_continuous: bool = True

    @model_validator(mode="after")
    def _human_mode_requires_person(self) -> "AutoSelectRequest":
        if self.mode == ScoringModeRequest.HUMAN and not self.person_cluster_id:
            raise ValueError(
                "person_cluster_id is required for human mode"
            )
        if self.min_duration_sec > self.target_duration_sec:
            raise ValueError(
                "min_duration_sec must be <= target_duration_sec"
            )
        return self


class ClipMemberResponse(BaseModel):
    """Per-scene span inside an AutoClip. Emitted so consumers can map
    directly to ``SceneClipSpec`` entries without re-fetching scene bounds.
    """

    scene_id: str = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)


class AutoClipResponse(BaseModel):
    """One auto-selected clip composed of one or more scenes.

    ``duration_ms`` is the SOURCE duration (sum of member scene durations),
    not the chronological span of ``start_ms``..``end_ms``. They differ
    when ``is_continuous=False`` (cherry-picked, non-adjacent scenes).

    ``members`` is the authoritative per-scene breakdown for rendering;
    ``scene_ids`` mirrors it for readability.
    """

    scene_ids: list[str] = Field(min_length=1)
    members: list[ClipMemberResponse] = Field(min_length=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    is_continuous: bool = True


class AutoSelectResponse(BaseModel):
    video_id: str
    mode: ScoringModeRequest
    clips: list[AutoClipResponse] = Field(default_factory=list)
    total_duration_ms: int = Field(default=0, ge=0)
    skipped_reason: str | None = None
    # Which scorer actually produced ``clips``. "pure" is the deterministic
    # fallback; "llm" is the OpenAI picker. Frontend surfaces this as a
    # small chip so users know when AI picked their clips.
    scorer: Literal["pure", "llm"] = "pure"


class AutoRenderRequest(AutoSelectRequest):
    title: str | None = Field(default=None, max_length=255)
    # Auto-caption is gated by AUTO_SHORTS_AUTOCAPTION_ENABLED (P4) AND
    # this per-request opt-in. Until P4 ships, the service rejects True
    # with 422 even if the global flag flips.
    auto_caption: bool = False
