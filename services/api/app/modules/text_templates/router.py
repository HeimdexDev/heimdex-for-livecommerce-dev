from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import get_text_template_repository
from app.modules.auth.service import get_current_user
from app.modules.text_templates.repository import TextTemplateRepository
from app.modules.text_templates.schemas import (
    TextTemplateCreate,
    TextTemplateListResponse,
    TextTemplateResponse,
    TextTemplateUpdate,
)
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

router = APIRouter(prefix="/text-templates", tags=["text-templates"])


@router.post("", response_model=TextTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TextTemplateCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[TextTemplateRepository, Depends(get_text_template_repository)],
):
    user_id = cast(UUID, user.id)
    template = await repo.create(org_ctx.org_id, user_id, body)
    return TextTemplateResponse.model_validate(template)


@router.get("", response_model=TextTemplateListResponse)
async def list_templates(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[TextTemplateRepository, Depends(get_text_template_repository)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    user_id = cast(UUID, user.id)
    templates, total = await repo.list_for_user(org_ctx.org_id, user_id, limit, offset)
    return TextTemplateListResponse(
        items=[TextTemplateResponse.model_validate(t) for t in templates],
        total=total,
    )


@router.get("/{template_id}", response_model=TextTemplateResponse)
async def get_template(
    template_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[TextTemplateRepository, Depends(get_text_template_repository)],
):
    template = await repo.get_by_id(org_ctx.org_id, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    return TextTemplateResponse.model_validate(template)


@router.patch("/{template_id}", response_model=TextTemplateResponse)
async def update_template(
    template_id: UUID,
    body: TextTemplateUpdate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[TextTemplateRepository, Depends(get_text_template_repository)],
):
    # Check if template exists first to distinguish 404 from 403
    existing = await repo.get_by_id(org_ctx.org_id, template_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if existing.is_system_preset:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot modify system preset")

    template = await repo.update(org_ctx.org_id, template_id, body)
    return TextTemplateResponse.model_validate(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[TextTemplateRepository, Depends(get_text_template_repository)],
):
    existing = await repo.get_by_id(org_ctx.org_id, template_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    if existing.is_system_preset:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot delete system preset")

    await repo.delete(org_ctx.org_id, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
