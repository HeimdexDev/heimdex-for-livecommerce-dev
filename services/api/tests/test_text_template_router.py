"""Tests for text template router endpoints."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_text_template_repository
from app.modules.auth import get_current_user
from app.modules.text_templates.router import router as text_templates_router
from app.modules.text_templates.schemas import TextTemplateResponse
from app.modules.tenancy import OrgContext, get_current_org


ORG_ID = uuid4()
USER_ID = uuid4()


def _template_obj(
    *,
    name: str = "Test Template",
    is_system_preset: bool = False,
    template_id=None,
    user_id=None,
):
    return SimpleNamespace(
        id=template_id or uuid4(),
        org_id=ORG_ID,
        user_id=user_id or USER_ID,
        name=name,
        font_family="Noto Sans KR",
        font_size_px=48,
        font_color="#FFFFFF",
        font_weight=700,
        line_height=1.4,
        letter_spacing=0,
        position_x=0.5,
        position_y=0.85,
        text_align="center",
        shadow_enabled=True,
        shadow_color="#000000",
        shadow_offset_x=2,
        shadow_offset_y=2,
        shadow_blur=4,
        background_enabled=False,
        background_color=None,
        background_padding=8,
        is_system_preset=is_system_preset,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _build_app(mock_repo: MagicMock) -> FastAPI:
    app = FastAPI()
    app.include_router(text_templates_router, prefix="/api")

    async def _mock_org() -> OrgContext:
        return OrgContext(org_id=ORG_ID, org_slug="testorg")

    async def _mock_user() -> SimpleNamespace:
        return SimpleNamespace(id=USER_ID)

    async def _mock_repo_fn() -> MagicMock:
        return mock_repo

    app.dependency_overrides[get_current_org] = _mock_org
    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_text_template_repository] = _mock_repo_fn

    return app


class TestCreateTemplate:
    def test_create_returns_201(self) -> None:
        repo = MagicMock()
        repo.create = AsyncMock(return_value=_template_obj())
        client = TestClient(_build_app(repo))

        resp = client.post("/api/text-templates", json={"name": "My Template"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Template"

    def test_create_without_auth_returns_401(self) -> None:
        from fastapi import HTTPException, status as http_status

        app = FastAPI()
        app.include_router(text_templates_router, prefix="/api")

        async def _mock_org() -> OrgContext:
            return OrgContext(org_id=ORG_ID, org_slug="testorg")

        async def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED)

        async def _mock_repo_fn() -> MagicMock:
            return MagicMock()

        app.dependency_overrides[get_current_org] = _mock_org
        app.dependency_overrides[get_current_user] = _no_auth
        app.dependency_overrides[get_text_template_repository] = _mock_repo_fn

        client = TestClient(app)
        resp = client.post("/api/text-templates", json={"name": "Test"})
        assert resp.status_code == 401


class TestListTemplates:
    def test_list_returns_templates(self) -> None:
        repo = MagicMock()
        templates = [_template_obj(is_system_preset=True), _template_obj()]
        repo.list_for_user = AsyncMock(return_value=(templates, 2))
        client = TestClient(_build_app(repo))

        resp = client.get("/api/text-templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2


class TestGetTemplate:
    def test_get_returns_200(self) -> None:
        tid = uuid4()
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=_template_obj(template_id=tid))
        client = TestClient(_build_app(repo))

        resp = client.get(f"/api/text-templates/{tid}")
        assert resp.status_code == 200

    def test_get_not_found_returns_404(self) -> None:
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=None)
        client = TestClient(_build_app(repo))

        resp = client.get(f"/api/text-templates/{uuid4()}")
        assert resp.status_code == 404


class TestUpdateTemplate:
    def test_update_user_template_returns_200(self) -> None:
        tid = uuid4()
        repo = MagicMock()
        obj = _template_obj(template_id=tid, is_system_preset=False)
        updated_obj = _template_obj(template_id=tid, name="Updated")
        repo.get_by_id = AsyncMock(return_value=obj)
        repo.update = AsyncMock(return_value=updated_obj)
        client = TestClient(_build_app(repo))

        resp = client.patch(f"/api/text-templates/{tid}", json={"name": "Updated"})
        assert resp.status_code == 200

    def test_update_system_preset_returns_403(self) -> None:
        tid = uuid4()
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=_template_obj(template_id=tid, is_system_preset=True))
        client = TestClient(_build_app(repo))

        resp = client.patch(f"/api/text-templates/{tid}", json={"name": "Changed"})
        assert resp.status_code == 403


class TestDeleteTemplate:
    def test_delete_user_template_returns_204(self) -> None:
        tid = uuid4()
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=_template_obj(template_id=tid, is_system_preset=False))
        repo.delete = AsyncMock(return_value=True)
        client = TestClient(_build_app(repo))

        resp = client.delete(f"/api/text-templates/{tid}")
        assert resp.status_code == 204

    def test_delete_system_preset_returns_403(self) -> None:
        tid = uuid4()
        repo = MagicMock()
        repo.get_by_id = AsyncMock(return_value=_template_obj(template_id=tid, is_system_preset=True))
        client = TestClient(_build_app(repo))

        resp = client.delete(f"/api/text-templates/{tid}")
        assert resp.status_code == 403

    def test_delete_without_auth_returns_401(self) -> None:
        from fastapi import HTTPException, status as http_status

        app = FastAPI()
        app.include_router(text_templates_router, prefix="/api")

        async def _mock_org() -> OrgContext:
            return OrgContext(org_id=ORG_ID, org_slug="testorg")

        async def _no_auth():
            raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED)

        async def _mock_repo_fn() -> MagicMock:
            return MagicMock()

        app.dependency_overrides[get_current_org] = _mock_org
        app.dependency_overrides[get_current_user] = _no_auth
        app.dependency_overrides[get_text_template_repository] = _mock_repo_fn

        client = TestClient(app)
        resp = client.delete(f"/api/text-templates/{uuid4()}")
        assert resp.status_code == 401
