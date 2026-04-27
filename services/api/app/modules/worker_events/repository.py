from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.modules.orgs.models import Org

from .models import WorkerEvent

logger = get_logger(__name__)


class WorkerEventRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        service: str,
        event_name: str,
        category: str,
        level: str,
        org_id: UUID | None = None,
        job_id: UUID | None = None,
        video_id: UUID | None = None,
        duration_ms: int | None = None,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkerEvent:
        event = WorkerEvent(
            service=service,
            event_name=event_name,
            category=category,
            level=level,
            org_id=org_id,
            job_id=job_id,
            video_id=video_id,
            duration_ms=duration_ms,
            message=message,
            metadata_=metadata or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_by_date_range_with_labels(
        self,
        *,
        date_from: datetime,
        date_to: datetime,
        limit: int = 100_000,
    ) -> list[tuple[WorkerEvent, str | None]]:
        """Return (event, org_name) tuples for export."""
        stmt = (
            select(WorkerEvent, Org.name)
            .outerjoin(Org, WorkerEvent.org_id == Org.id)
            .where(
                WorkerEvent.created_at >= date_from,
                WorkerEvent.created_at < date_to,
            )
            .order_by(WorkerEvent.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.all())

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

            partition_name = f"worker_events_{year}_{month:02d}"
            from_date = f"{year}-{month:02d}-01"
            to_date = f"{next_year}-{next_month:02d}-01"

            await self.session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} "
                    f"PARTITION OF worker_events "
                    f"FOR VALUES FROM ('{from_date}') TO ('{to_date}')"
                )
            )
            created.append(partition_name)

        await self.session.flush()
        logger.info(
            "worker_event_partitions_ensured",
            partitions=created,
            months_ahead=months_ahead,
        )
        return created
