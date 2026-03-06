from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from .models import SearchEvent

logger = get_logger(__name__)


class SearchEventRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        org_id: UUID,
        user_id: UUID,
        query_text: str,
        search_mode: str,
        result_count: int | None = None,
        response_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SearchEvent:
        event = SearchEvent(
            org_id=org_id,
            user_id=user_id,
            query_text=query_text,
            search_mode=search_mode,
            result_count=result_count,
            response_ms=response_ms,
            metadata_=metadata or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_by_date_range(
        self,
        *,
        org_id: UUID | None = None,
        date_from: datetime,
        date_to: datetime,
        limit: int = 10_000,
    ) -> list[SearchEvent]:
        stmt = (
            select(SearchEvent)
            .where(
                SearchEvent.created_at >= date_from,
                SearchEvent.created_at < date_to,
            )
            .order_by(SearchEvent.created_at.asc())
            .limit(limit)
        )
        if org_id is not None:
            stmt = stmt.where(SearchEvent.org_id == org_id)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_org(
        self,
        org_id: UUID,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(SearchEvent)
            .where(SearchEvent.org_id == org_id)
        )
        if date_from is not None:
            stmt = stmt.where(SearchEvent.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(SearchEvent.created_at < date_to)

        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def ensure_partitions(self, months_ahead: int = 2) -> list[str]:
        """Idempotent partition creation for current month + N months ahead.

        Must be called on every startup — partitioned tables reject inserts
        into date ranges without a matching partition.
        """
        now = datetime.now(timezone.utc)
        created: list[str] = []

        for offset in range(months_ahead + 1):
            month = now.month + offset
            year = now.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1

            next_month = month + 1
            next_year = year + (next_month - 1) // 12
            next_month = ((next_month - 1) % 12) + 1

            partition_name = f"search_events_{year}_{month:02d}"
            from_date = f"{year}-{month:02d}-01"
            to_date = f"{next_year}-{next_month:02d}-01"

            await self.session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} "
                    f"PARTITION OF search_events "
                    f"FOR VALUES FROM ('{from_date}') TO ('{to_date}')"
                )
            )
            created.append(partition_name)

        await self.session.flush()
        logger.info(
            "search_event_partitions_ensured",
            partitions=created,
            months_ahead=months_ahead,
        )
        return created
