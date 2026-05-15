from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TextTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    font_family: str = "Noto Sans KR"
    font_size_px: int = Field(48, ge=12, le=120)
    font_color: str = "#FFFFFF"
    font_weight: int = Field(700, ge=100, le=900)
    line_height: float = Field(1.4, ge=0.5, le=3.0)
    letter_spacing: float = Field(0, ge=-5.0, le=20.0)
    position_x: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Horizontal position ratio (0.0=left, 1.0=right). Ignored when text_align='center'.",
    )
    position_y: float = Field(
        0.85, ge=0.0, le=1.0,
        description="Vertical position ratio (0.0=top, 1.0=bottom). Text top edge starts at height * position_y.",
    )
    text_align: str = "center"
    shadow_enabled: bool = True
    shadow_color: str = "#000000"
    shadow_offset_x: int = 2
    shadow_offset_y: int = 2
    shadow_blur: int = Field(4, ge=0)
    background_enabled: bool = False
    background_color: str | None = None
    background_padding: int = Field(8, ge=0)


class TextTemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    font_family: str | None = None
    font_size_px: int | None = Field(None, ge=12, le=120)
    font_color: str | None = None
    font_weight: int | None = Field(None, ge=100, le=900)
    line_height: float | None = Field(None, ge=0.5, le=3.0)
    letter_spacing: float | None = Field(None, ge=-5.0, le=20.0)
    position_x: float | None = Field(None, ge=0.0, le=1.0)
    position_y: float | None = Field(None, ge=0.0, le=1.0)
    text_align: str | None = None
    shadow_enabled: bool | None = None
    shadow_color: str | None = None
    shadow_offset_x: int | None = None
    shadow_offset_y: int | None = None
    shadow_blur: int | None = Field(None, ge=0)
    background_enabled: bool | None = None
    background_color: str | None = None
    background_padding: int | None = Field(None, ge=0)


class TextTemplateResponse(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID | None
    name: str
    font_family: str
    font_size_px: int
    font_color: str
    font_weight: int
    line_height: float
    letter_spacing: float
    position_x: float
    position_y: float
    text_align: str
    shadow_enabled: bool
    shadow_color: str
    shadow_offset_x: int
    shadow_offset_y: int
    shadow_blur: int
    background_enabled: bool
    background_color: str | None
    background_padding: int
    is_system_preset: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TextTemplateListResponse(BaseModel):
    items: list[TextTemplateResponse]
    total: int
