"""
Pydantic schemas for the scene grouping endpoint.

These schemas define the API contract. SceneGroup.scenes reuses the
existing VideoScene model from the videos module — the only cross-module
reference, via a shared Pydantic model (not a service or repository).
"""

from pydantic import BaseModel, Field

from app.modules.videos.schemas import VideoScene


class SceneGroup(BaseModel):
    """A group of consecutive, semantically related scenes."""

    group_index: int = Field(description="Zero-based group position in the video")
    start_ms: int = Field(description="Start time of the first scene in the group")
    end_ms: int = Field(description="End time of the last scene in the group")
    scene_count: int = Field(description="Number of scenes in this group")
    representative_scene_id: str = Field(
        description="Scene ID of the representative scene (middle of group)"
    )
    scenes: list[VideoScene] = Field(
        default_factory=list,
        description="Individual scenes within this group",
    )


class SceneGroupsResponse(BaseModel):
    """Response for the scene grouping endpoint."""

    video_id: str
    total_groups: int = 0
    total_scenes: int = 0
    groups: list[SceneGroup] = Field(default_factory=list)
