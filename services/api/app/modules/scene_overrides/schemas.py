from pydantic import BaseModel, Field

EDITABLE_FIELDS = {"scene_caption", "transcript_raw", "speaker_transcript", "ai_tags"}


class SceneOverrideRequest(BaseModel):
    """PATCH request — only provided (non-None) fields are overridden."""

    scene_caption: str | None = None
    transcript_raw: str | None = None
    speaker_transcript: str | None = None
    ai_tags: list[str] | None = None


class SceneOverrideResponse(BaseModel):
    scene_id: str
    overridden_fields: list[str] = Field(default_factory=list)
    updated_at: str
