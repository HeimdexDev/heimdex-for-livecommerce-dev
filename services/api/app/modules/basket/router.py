from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_basket_repository
from app.modules.auth.service import get_current_user
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

from .models import SceneBasket, SceneBasketItem
from .repository import SceneBasketRepository
from .schemas import (
    BasketCreate,
    BasketItemCreate,
    BasketItemResponse,
    BasketListResponse,
    BasketResponse,
    ReorderRequest,
)

router = APIRouter(prefix="/baskets", tags=["baskets"])


def _to_item_response(item: SceneBasketItem) -> BasketItemResponse:
    return BasketItemResponse(
        id=cast(UUID, item.id),
        scene_id=item.scene_id,
        video_id=item.video_id,
        video_title=item.video_title,
        start_ms=item.start_ms,
        end_ms=item.end_ms,
        sort_order=item.sort_order,
        label=item.label,
        thumbnail_url=item.thumbnail_url,
    )


def _to_basket_response(basket: SceneBasket, items: list[SceneBasketItem]) -> BasketResponse:
    item_responses = [_to_item_response(item) for item in items]
    return BasketResponse(
        id=cast(UUID, basket.id),
        name=basket.name,
        items=item_responses,
        item_count=len(item_responses),
        created_at=basket.created_at,
    )


@router.post("", response_model=BasketResponse, status_code=status.HTTP_201_CREATED)
async def create_basket(
    body: BasketCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SceneBasketRepository, Depends(get_basket_repository)],
):
    basket = await repo.create_basket(
        org_id=org_ctx.org_id,
        user_id=cast(UUID, user.id),
        name=body.name,
    )
    return _to_basket_response(basket, items=[])


@router.get("", response_model=BasketListResponse)
async def list_baskets(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SceneBasketRepository, Depends(get_basket_repository)],
):
    user_id = cast(UUID, user.id)
    baskets = await repo.list_baskets(org_ctx.org_id, user_id)

    basket_responses: list[BasketResponse] = []
    for basket in baskets:
        items = await repo.get_items(org_id=org_ctx.org_id, basket_id=cast(UUID, basket.id))
        basket_responses.append(_to_basket_response(basket, items))

    return BasketListResponse(baskets=basket_responses, total=len(basket_responses))


@router.get("/{basket_id}", response_model=BasketResponse)
async def get_basket(
    basket_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SceneBasketRepository, Depends(get_basket_repository)],
):
    basket = await repo.get_basket(basket_id, org_ctx.org_id)
    if basket is None or basket.user_id != cast(UUID, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Basket not found")

    items = await repo.get_items(org_id=org_ctx.org_id, basket_id=basket_id)
    return _to_basket_response(basket, items)


@router.post("/{basket_id}/items", response_model=BasketResponse)
async def add_basket_items(
    basket_id: UUID,
    body: list[BasketItemCreate],
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SceneBasketRepository, Depends(get_basket_repository)],
):
    basket = await repo.get_basket(basket_id, org_ctx.org_id)
    if basket is None or basket.user_id != cast(UUID, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Basket not found")

    _ = await repo.add_items(
        org_id=org_ctx.org_id,
        basket_id=basket_id,
        items=body,
    )
    items = await repo.get_items(org_id=org_ctx.org_id, basket_id=basket_id)
    return _to_basket_response(basket, items)


@router.delete("/{basket_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_basket_item(
    basket_id: UUID,
    item_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SceneBasketRepository, Depends(get_basket_repository)],
):
    basket = await repo.get_basket(basket_id, org_ctx.org_id)
    if basket is None or basket.user_id != cast(UUID, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Basket not found")

    deleted = await repo.remove_item(org_id=org_ctx.org_id, basket_id=basket_id, item_id=item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Basket item not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{basket_id}/items/reorder", response_model=BasketResponse)
async def reorder_basket_items(
    basket_id: UUID,
    body: ReorderRequest,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SceneBasketRepository, Depends(get_basket_repository)],
):
    basket = await repo.get_basket(basket_id, org_ctx.org_id)
    if basket is None or basket.user_id != cast(UUID, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Basket not found")

    reordered = await repo.reorder_items(
        org_id=org_ctx.org_id,
        basket_id=basket_id,
        item_ids=body.item_ids,
    )
    if not reordered:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reorder payload")

    items = await repo.get_items(org_id=org_ctx.org_id, basket_id=basket_id)
    return _to_basket_response(basket, items)


@router.delete("/{basket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_basket(
    basket_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    repo: Annotated[SceneBasketRepository, Depends(get_basket_repository)],
):
    basket = await repo.get_basket(basket_id, org_ctx.org_id)
    if basket is None or basket.user_id != cast(UUID, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Basket not found")

    await repo.delete_basket(basket)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
