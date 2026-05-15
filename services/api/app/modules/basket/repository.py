from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SceneBasket, SceneBasketItem
from .schemas import BasketItemCreate


class SceneBasketRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create_basket(self, *, org_id: UUID, user_id: UUID, name: str) -> SceneBasket:
        basket = SceneBasket(org_id=org_id, user_id=user_id, name=name)
        self.session.add(basket)
        await self.session.flush()
        return basket

    async def get_basket(self, basket_id: UUID, org_id: UUID) -> SceneBasket | None:
        result = await self.session.execute(
            select(SceneBasket).where(
                SceneBasket.id == basket_id,
                SceneBasket.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_baskets(self, org_id: UUID, user_id: UUID, limit: int = 200) -> list[SceneBasket]:
        result = await self.session.execute(
            select(SceneBasket)
            .where(
                SceneBasket.org_id == org_id,
                SceneBasket.user_id == user_id,
            )
            .order_by(SceneBasket.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_items(
        self,
        *,
        org_id: UUID,
        basket_id: UUID,
        items: list[BasketItemCreate],
    ) -> list[SceneBasketItem]:
        max_order_result = await self.session.execute(
            select(func.max(SceneBasketItem.sort_order))
            .select_from(SceneBasketItem)
            .join(SceneBasket, SceneBasket.id == SceneBasketItem.basket_id)
            .where(
                SceneBasket.id == basket_id,
                SceneBasket.org_id == org_id,
            )
        )
        max_order = max_order_result.scalar_one_or_none()
        next_order = 0 if max_order is None else max_order + 1

        created: list[SceneBasketItem] = []
        for payload in items:
            item = SceneBasketItem(
                basket_id=basket_id,
                scene_id=payload.scene_id,
                video_id=payload.video_id,
                video_title=payload.video_title,
                start_ms=payload.start_ms,
                end_ms=payload.end_ms,
                sort_order=next_order,
                label=payload.label,
                thumbnail_url=payload.thumbnail_url,
            )
            self.session.add(item)
            created.append(item)
            next_order += 1

        await self.session.flush()
        return created

    async def remove_item(self, *, org_id: UUID, basket_id: UUID, item_id: UUID) -> bool:
        result = await self.session.execute(
            select(SceneBasketItem)
            .join(SceneBasket, SceneBasket.id == SceneBasketItem.basket_id)
            .where(
                SceneBasketItem.id == item_id,
                SceneBasketItem.basket_id == basket_id,
                SceneBasket.org_id == org_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return False

        await self.session.delete(item)
        await self.session.flush()
        return True

    async def reorder_items(
        self,
        *,
        org_id: UUID,
        basket_id: UUID,
        item_ids: list[UUID],
    ) -> bool:
        result = await self.session.execute(
            select(SceneBasketItem)
            .join(SceneBasket, SceneBasket.id == SceneBasketItem.basket_id)
            .where(
                SceneBasketItem.basket_id == basket_id,
                SceneBasket.org_id == org_id,
            )
        )
        current_items = list(result.scalars().all())
        if not current_items:
            return False

        ids_in_basket = {cast(UUID, item.id) for item in current_items}
        requested_ids = set(item_ids)
        if ids_in_basket != requested_ids:
            return False

        by_id = {cast(UUID, item.id): item for item in current_items}
        for sort_order, item_id in enumerate(item_ids):
            by_id[item_id].sort_order = sort_order

        await self.session.flush()
        return True

    async def get_items(self, *, org_id: UUID, basket_id: UUID) -> list[SceneBasketItem]:
        result = await self.session.execute(
            select(SceneBasketItem)
            .join(SceneBasket, SceneBasket.id == SceneBasketItem.basket_id)
            .where(
                SceneBasketItem.basket_id == basket_id,
                SceneBasket.org_id == org_id,
            )
            .order_by(SceneBasketItem.sort_order.asc(), SceneBasketItem.created_at.asc())
        )
        return list(result.scalars().all())

    async def delete_basket(self, basket: SceneBasket) -> None:
        await self.session.delete(basket)
        await self.session.flush()
