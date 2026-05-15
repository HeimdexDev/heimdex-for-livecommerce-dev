"""Pydantic schemas for the subtitle presets API.

The ``style_json`` field on create/update is validated against the contracts
spec types (``TextOverlaySpec`` / ``BackgroundOverlaySpec``) so the persisted
blob is guaranteed to round-trip cleanly back into the editor. Only the
*style* fragment is stored — id, timing, position, and layer_index are
overlay-instance properties, not preset properties.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from heimdex_media_contracts.composition import (
    BackgroundOverlaySpec,
    TextOverlaySpec,
)

PresetKind = Literal["text", "background"]


# --- Style validation helpers -----------------------------------------------


# Fields on the contracts overlay spec that are part of an overlay's identity
# / placement, not its style. We strip these from the stored JSON so a preset
# applied to overlay A doesn't drag overlay B's identity along with it.
_IDENTITY_FIELDS = {"id", "kind", "start_ms", "end_ms", "layer_index", "transform"}


def _validate_style_json(kind: PresetKind, style_json: dict[str, Any]) -> dict[str, Any]:
    """Coerce + validate a style_json blob against the contracts spec.

    Constructs a full TextOverlaySpec or BackgroundOverlaySpec by filling in
    placeholder identity fields, then dumps the result and strips identity
    fields back out. Any contracts-side validation error (bad hex color,
    out-of-range size, unknown enum value) propagates as a 422 to the client.
    """
    placeholder_identity = {
        "id": "preset-validation",
        "start_ms": 0,
        "end_ms": 1,
    }
    if kind == "text":
        merged = {"kind": "text", **placeholder_identity, **style_json}
        spec = TextOverlaySpec(**merged)
    else:
        # Background needs explicit transform.width_px/height_px to validate.
        # Pass through whatever the caller supplied (may be None — error path
        # exercised in test_router).
        transform = style_json.get("transform") or {}
        merged = {
            "kind": "background",
            **placeholder_identity,
            **style_json,
            "transform": {"width_px": 100, "height_px": 100, **transform},
        }
        spec = BackgroundOverlaySpec(**merged)
    dumped = spec.model_dump(mode="json")
    return {k: v for k, v in dumped.items() if k not in _IDENTITY_FIELDS}


# --- Request schemas --------------------------------------------------------


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: PresetKind
    style_json: dict[str, Any]
    is_shared: bool = False

    @model_validator(mode="after")
    def _validate_style_against_contracts(self) -> "PresetCreate":
        self.style_json = _validate_style_json(self.kind, self.style_json)
        return self


class PresetUpdate(BaseModel):
    """All fields optional — patch semantics."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    style_json: dict[str, Any] | None = None
    is_shared: bool | None = None

    # Note: kind cannot be changed — would invalidate stored style_json.
    # The frontend deletes + recreates if it really wants to convert.

    def validated_style_json(self, kind: PresetKind) -> dict[str, Any] | None:
        if self.style_json is None:
            return None
        return _validate_style_json(kind, self.style_json)


# --- Response schemas -------------------------------------------------------


class PresetResponse(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID
    name: str
    kind: PresetKind
    style_json: dict[str, Any]
    is_shared: bool
    is_owned: bool  # True if the requesting user is the creator
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PresetListResponse(BaseModel):
    items: list[PresetResponse]
    total: int


__all__ = [
    "PresetCreate",
    "PresetKind",
    "PresetListResponse",
    "PresetResponse",
    "PresetUpdate",
]
