from typing import Literal

from pydantic import BaseModel


class OrgSettingsResponse(BaseModel):
    """Organization settings response with merged defaults."""

    thumbnail_aspect_ratio: str
    split_preset: str


class OrgSettingsUpdateRequest(BaseModel):
    """Organization settings update request."""

    thumbnail_aspect_ratio: Literal["16:9", "9:16"] | None = None
    split_preset: Literal["default", "fine", "coarse", "visual_only"] | None = None
