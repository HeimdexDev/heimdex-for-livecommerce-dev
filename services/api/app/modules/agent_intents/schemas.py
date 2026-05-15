from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateIntentRequest(BaseModel):
    type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-z_]+$",
        description="Intent type, e.g. folder_add",
    )
    device_id: UUID = Field(
        ...,
        description="Target device ID (required, intent is bound to this device)",
    )


class CreateIntentResponse(BaseModel):
    intent_code: str
    type: str
    expires_at: datetime
    deep_link_url: str


class ExchangeIntentRequest(BaseModel):
    intent_code: str = Field(
        ...,
        min_length=20,
        max_length=64,
        description="Intent code from deep link",
    )


class ExchangeIntentResponse(BaseModel):
    type: str
    org_id: UUID
    payload: dict[str, object]


class IntentListItem(BaseModel):
    id: UUID
    type: str
    used: bool
    expires_at: datetime
    created_at: datetime
    created_by: UUID


class IntentListResponse(BaseModel):
    intents: list[IntentListItem]
