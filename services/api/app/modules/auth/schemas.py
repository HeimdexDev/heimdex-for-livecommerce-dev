from uuid import UUID

from pydantic import BaseModel, EmailStr


class TokenPayload(BaseModel):
    sub: str
    org_id: str
    user_id: str
    email: str
    role: str
    exp: int


class MeResponse(BaseModel):
    user_id: str
    email: str
    role: str


class DevLoginRequest(BaseModel):
    email: EmailStr


class DevLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID
    org_id: UUID
    org_slug: str
