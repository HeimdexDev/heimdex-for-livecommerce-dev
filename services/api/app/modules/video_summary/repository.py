"""Database operations for video summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.video_summary.models import VideoSummary


class VideoSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_video(self, org_id: UUID, video_id: str) -> VideoSummary | None:
        stmt = select(VideoSummary).where(
            VideoSummary.org_id == org_id,
            VideoSummary.video_id == video_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert(
        self,
        org_id: UUID,
        video_id: str,
        summary: str,
        model: str,
        prompt_version: str,
        scene_count: int,
        input_hash: str,
    ) -> VideoSummary:
        existing = await self.get_by_video(org_id, video_id)
        if existing is not None:
            existing.summary = summary
            existing.model = model
            existing.prompt_version = prompt_version
            existing.scene_count = scene_count
            existing.input_hash = input_hash
            return existing

        record = VideoSummary(
            org_id=org_id,
            video_id=video_id,
            summary=summary,
            model=model,
            prompt_version=prompt_version,
            scene_count=scene_count,
            input_hash=input_hash,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def set_override(
        self,
        org_id: UUID,
        video_id: str,
        override_text: str,
        user_id: UUID,
    ) -> VideoSummary | None:
        record = await self.get_by_video(org_id, video_id)
        if record is None:
            return None
        record.summary_override = override_text
        record.edited_by = user_id
        record.edited_at = datetime.now(timezone.utc)
        return record

    async def clear_override(self, org_id: UUID, video_id: str) -> VideoSummary | None:
        record = await self.get_by_video(org_id, video_id)
        if record is None:
            return None
        record.summary_override = None
        record.edited_by = None
        record.edited_at = None
        return record
