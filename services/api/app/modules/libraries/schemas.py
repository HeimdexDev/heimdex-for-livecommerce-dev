"""
Pydantic schemas for library management endpoints.

These DTOs define the contract for agent library creation and listing.
The agent uses POST /api/libraries to get-or-create libraries by name,
and GET /api/libraries to list all libraries in the org.
"""
from uuid import UUID

from pydantic import BaseModel, Field


class CreateLibraryRequest(BaseModel):
    """Request body for POST /api/libraries."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Library name (unique within org)",
    )


class LibraryResponse(BaseModel):
    """Response model for a single library."""

    id: UUID = Field(..., description="Library UUID")
    name: str = Field(..., description="Library name")
    created: bool = Field(
        ...,
        description="True if newly created, False if existing was returned",
    )


class LibraryListResponse(BaseModel):
    """Response body for GET /api/libraries."""

    libraries: list[LibraryResponse] = Field(
        ...,
        description="List of libraries in the org",
    )
