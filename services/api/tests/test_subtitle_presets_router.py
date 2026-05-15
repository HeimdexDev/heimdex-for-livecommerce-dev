"""Tests for subtitle_presets router endpoints.

Mirrors the pattern in test_shorts_render_router.py — TestClient over a
FastAPI app with dependency overrides for org / user / service.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_subtitle_preset_service
from app.modules.auth import get_current_user
from app.modules.subtitle_presets.rate_limit import (
    require_subtitle_preset_rate_limit,
    reset as reset_rate_limit,
)
from app.modules.subtitle_presets.router import router as presets_router
from app.modules.subtitle_presets.schemas import (
    PresetListResponse,
    PresetResponse,
)
from app.modules.tenancy import OrgContext, get_current_org

ORG_ID = uuid4()
USER_ID = uuid4()
OTHER_USER_ID = uuid4()


def _preset_response(
    *,
    preset_id=None,
    name: str = "Headline",
    kind: str = "text",
    is_shared: bool = False,
    is_owned: bool = True,
    user_id=None,
) -> PresetResponse:
    pid = preset_id or uuid4()
    return PresetResponse(
        id=pid,
        org_id=ORG_ID,
        user_id=user_id or USER_ID,
        name=name,
        kind=kind,  # pyright: ignore[reportArgumentType]
        style_json={"font_family": "Pretendard", "font_size_px": 36},
        is_shared=is_shared,
        is_owned=is_owned,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _build_app(mock_service: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(presets_router, prefix="/api")

    async def _mock_org() -> OrgContext:
        return OrgContext(org_id=ORG_ID, org_slug="testorg")

    async def _mock_user() -> SimpleNamespace:
        return SimpleNamespace(id=USER_ID)

    async def _mock_service_fn() -> MagicMock:
        return mock_service

    # Disable the rate-limit dependency for routing tests (it has its own
    # dedicated test_subtitle_presets_rate_limit module).
    async def _no_rate_limit() -> None:
        return None

    app.dependency_overrides[get_current_org] = _mock_org
    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_subtitle_preset_service] = _mock_service_fn
    app.dependency_overrides[require_subtitle_preset_rate_limit] = _no_rate_limit

    return app


def _valid_text_create_payload() -> dict:
    return {
        "name": "Headline",
        "kind": "text",
        "style_json": {
            "text": "라이브 특가",
            "font_family": "Pretendard",
            "font_size_px": 48,
            "italic": True,
            "font_color": "#FF00FF",
        },
        "is_shared": False,
    }


def _valid_bg_create_payload() -> dict:
    return {
        "name": "DarkBand",
        "kind": "background",
        "style_json": {
            "fill_color": "#1a1a1a",
            "transform": {"width_px": 400, "height_px": 80},
        },
        "is_shared": True,
    }


def setup_function() -> None:
    # Each test starts with empty rate-limit buckets to avoid cross-test bleed.
    reset_rate_limit()


# --- LIST -------------------------------------------------------------------

def test_list_returns_visible_presets() -> None:
    mock_service = MagicMock()
    items = [_preset_response(name="A"), _preset_response(name="B")]
    mock_service.list = AsyncMock(
        return_value=PresetListResponse(items=items, total=2)
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.get("/api/shorts/presets")

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_list_filters_by_kind() -> None:
    mock_service = MagicMock()
    mock_service.list = AsyncMock(
        return_value=PresetListResponse(items=[], total=0)
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.get("/api/shorts/presets?kind=background")

    assert r.status_code == 200
    mock_service.list.assert_called_once()
    assert mock_service.list.call_args.kwargs["kind"] == "background"


def test_list_rejects_invalid_kind() -> None:
    mock_service = MagicMock()
    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.get("/api/shorts/presets?kind=invalid")
    assert r.status_code == 422


def test_list_passes_pagination_params() -> None:
    mock_service = MagicMock()
    mock_service.list = AsyncMock(
        return_value=PresetListResponse(items=[], total=0)
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.get("/api/shorts/presets?limit=50&offset=10")

    assert r.status_code == 200
    kwargs = mock_service.list.call_args.kwargs
    assert kwargs["limit"] == 50
    assert kwargs["offset"] == 10
    assert kwargs["org_id"] == ORG_ID
    assert kwargs["user_id"] == USER_ID


# --- CREATE -----------------------------------------------------------------

def test_create_text_preset_returns_201() -> None:
    mock_service = MagicMock()
    mock_service.create = AsyncMock(
        return_value=_preset_response(name="Headline")
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.post("/api/shorts/presets", json=_valid_text_create_payload())

    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Headline"
    assert body["kind"] == "text"
    assert body["is_owned"] is True


def test_create_background_preset_returns_201() -> None:
    mock_service = MagicMock()
    mock_service.create = AsyncMock(
        return_value=_preset_response(name="DarkBand", kind="background", is_shared=True)
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.post("/api/shorts/presets", json=_valid_bg_create_payload())

    assert r.status_code == 201
    assert r.json()["is_shared"] is True


def test_create_rejects_bad_hex_color() -> None:
    mock_service = MagicMock()
    payload = _valid_text_create_payload()
    payload["style_json"]["font_color"] = "red"

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.post("/api/shorts/presets", json=payload)

    assert r.status_code == 422


def test_create_rejects_unknown_kind() -> None:
    mock_service = MagicMock()
    payload = _valid_text_create_payload()
    payload["kind"] = "image"

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.post("/api/shorts/presets", json=payload)

    assert r.status_code == 422


def test_create_rejects_empty_name() -> None:
    mock_service = MagicMock()
    payload = _valid_text_create_payload()
    payload["name"] = ""

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.post("/api/shorts/presets", json=payload)

    assert r.status_code == 422


# --- UPDATE -----------------------------------------------------------------

def test_update_owned_preset_returns_200() -> None:
    mock_service = MagicMock()
    pid = uuid4()
    mock_service.update = AsyncMock(
        return_value=_preset_response(preset_id=pid, name="Renamed")
    )

    app = _build_app(mock_service)
    with TestClient(app) as client:
        r = client.patch(
            f"/api/shorts/presets/{pid}",
            json={"name": "Renamed"},
        )

    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"


def test_update_non_owned_returns_403() -> None:
    from fastapi import HTTPException, status

    mock_service = MagicMock()
    mock_service.update = AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the preset owner can modify this preset",
        )
    )

    app = _build_app(mock_service)
    pid = uuid4()
    with TestClient(app) as client:
        r = client.patch(f"/api/shorts/presets/{pid}", json={"name": "Hi"})

    assert r.status_code == 403


def test_update_missing_returns_404() -> None:
    from fastapi import HTTPException, status

    mock_service = MagicMock()
    mock_service.update = AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found"
        )
    )

    app = _build_app(mock_service)
    pid = uuid4()
    with TestClient(app) as client:
        r = client.patch(f"/api/shorts/presets/{pid}", json={"name": "Hi"})

    assert r.status_code == 404


# --- DELETE -----------------------------------------------------------------

def test_delete_owned_returns_204() -> None:
    mock_service = MagicMock()
    mock_service.delete = AsyncMock(return_value=None)

    app = _build_app(mock_service)
    pid = uuid4()
    with TestClient(app) as client:
        r = client.delete(f"/api/shorts/presets/{pid}")

    assert r.status_code == 204


def test_delete_non_owned_returns_403() -> None:
    from fastapi import HTTPException, status

    mock_service = MagicMock()
    mock_service.delete = AsyncMock(
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the preset owner can delete this preset",
        )
    )

    app = _build_app(mock_service)
    pid = uuid4()
    with TestClient(app) as client:
        r = client.delete(f"/api/shorts/presets/{pid}")

    assert r.status_code == 403
