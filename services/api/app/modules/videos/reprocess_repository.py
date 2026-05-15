from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.videos.reprocess_models import SceneReprocessJob


class ReprocessRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def create(
        self,
        *,
        org_id: UUID,
        video_id: str,
        source_type: str,
        scene_params: dict[str, object],
        proxy_s3_key: str,
    ) -> SceneReprocessJob:
        record = SceneReprocessJob(
            org_id=org_id,
            video_id=video_id,
            source_type=source_type,
            scene_params=scene_params,
            proxy_s3_key=proxy_s3_key,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get(self, job_id: UUID, org_id: UUID) -> SceneReprocessJob | None:
        result = await self.session.execute(
            select(SceneReprocessJob).where(
                SceneReprocessJob.id == job_id,
                SceneReprocessJob.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, job_id: UUID) -> SceneReprocessJob | None:
        result = await self.session.execute(
            select(SceneReprocessJob).where(SceneReprocessJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_video(self, org_id: UUID, video_id: str) -> SceneReprocessJob | None:
        result = await self.session.execute(
            select(SceneReprocessJob)
            .where(
                SceneReprocessJob.org_id == org_id,
                SceneReprocessJob.video_id == video_id,
                SceneReprocessJob.status.in_(["pending", "processing"]),
            )
            .order_by(SceneReprocessJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_video(self, org_id: UUID, video_id: str) -> SceneReprocessJob | None:
        result = await self.session.execute(
            select(SceneReprocessJob)
            .where(
                SceneReprocessJob.org_id == org_id,
                SceneReprocessJob.video_id == video_id,
            )
            .order_by(SceneReprocessJob.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: UUID,
        status: str,
        *,
        scene_count: int | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if scene_count is not None:
            values["scene_count"] = scene_count
        if error is not None:
            values["error"] = error

        _ = await self.session.execute(
            update(SceneReprocessJob)
            .where(SceneReprocessJob.id == job_id)
            .values(**values)
        )
        await self.session.flush()
