"""ProductScanDailyCostRepository — per-org per-day cost ledger.

Separate budget bucket from auto_shorts_llm / image_caption /
video_summary so the cap and the dashboard stay interpretable per
feature. UPSERT pattern lets concurrent worker heartbeats and the
API's pre-flight check both write without losing increments.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.models import ProductScanDailyCost


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


class ProductScanDailyCostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    async def get_today_cost(self, *, org_id: UUID) -> Decimal:
        """Return the running cost for ``org_id`` on the current UTC
        day, or ``Decimal('0')`` if no row exists yet."""
        stmt = select(ProductScanDailyCost.cost_usd).where(
            ProductScanDailyCost.org_id == org_id,
            ProductScanDailyCost.day == _utc_today(),
        )
        value = (await self.session.execute(stmt)).scalar_one_or_none()
        return Decimal(value) if value is not None else Decimal("0")

    async def add_cost(self, *, org_id: UUID, delta_usd: Decimal) -> Decimal:
        """Atomically add ``delta_usd`` to today's row.

        Returns the new running total. Uses Postgres ``INSERT … ON
        CONFLICT DO UPDATE`` so concurrent updates from many workers
        on the same day never lose increments.
        """
        if delta_usd < Decimal("0"):
            raise ValueError("delta_usd must be non-negative")
        today = _utc_today()
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(ProductScanDailyCost)
            .values(org_id=org_id, day=today, cost_usd=delta_usd, updated_at=now)
            .on_conflict_do_update(
                index_elements=["org_id", "day"],
                set_={
                    "cost_usd": (
                        ProductScanDailyCost.cost_usd + delta_usd
                    ),
                    "updated_at": now,
                },
            )
            .returning(ProductScanDailyCost.cost_usd)
        )
        result = (await self.session.execute(stmt)).scalar_one()
        return Decimal(result)
