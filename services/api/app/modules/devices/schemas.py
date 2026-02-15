from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DeviceRegisterRequest(BaseModel):
    device_public_id: str = Field(
        ..., min_length=1, max_length=64, description="Client-generated device identifier"
    )
    device_name: str = Field(
        ..., min_length=1, max_length=255, description="Human-readable device name"
    )


class DeviceRegisterResponse(BaseModel):
    device_id: UUID
    device_public_id: str
    device_name: str
    device_secret: str  # Raw secret, only returned once
    created_at: datetime


class DeviceRotateRequest(BaseModel):
    device_public_id: str = Field(
        ..., min_length=1, max_length=64, description="Device public identifier"
    )


class DeviceRotateResponse(BaseModel):
    device_id: UUID
    device_public_id: str
    device_secret: str  # New raw secret
    rotated_at: datetime


class DeviceRevokeRequest(BaseModel):
    device_public_id: str = Field(
        ..., min_length=1, max_length=64, description="Device public identifier"
    )


class DeviceRevokeResponse(BaseModel):
    device_id: UUID
    device_public_id: str
    is_revoked: bool
    revoked_at: datetime


class DeviceListItem(BaseModel):
    device_id: UUID
    device_public_id: str
    device_name: str
    is_revoked: bool
    last_seen_at: datetime | None
    created_at: datetime


class DeviceListResponse(BaseModel):
    devices: list[DeviceListItem]


# --- Pairing code schemas ---


class PairingCodeCreateResponse(BaseModel):
    code: str
    expires_at: datetime


class PairingCodeExchangeRequest(BaseModel):
    code: str = Field(
        ..., min_length=6, max_length=6, pattern=r"^\d{6}$",
        description="6-digit pairing code",
    )
    device_public_id: str = Field(
        ..., min_length=1, max_length=64, description="Client-generated device identifier"
    )
    device_name: str = Field(
        ..., min_length=1, max_length=255, description="Human-readable device name"
    )
