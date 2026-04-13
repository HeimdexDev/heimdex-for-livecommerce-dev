"""ImageCaptionService — async background captioning inside the api container.

Runs as a FastAPI background task (fire-and-forget via asyncio.create_task)
rather than as a separate SQS worker. See ./README.md for the rationale.

Public surface:
    schedule_image_caption_task(org_id, video_id, scenes) -> None
        Fire-and-forget entrypoint. Creates an asyncio task, retains a
        strong reference to prevent GC, logs failures. Safe to call
        from any async request handler.

    build_service(settings) -> ImageCaptionService | None
        Factory. Returns None if image_caption_enabled is False so the
        caller can short-circuit without constructing an engine.

Decoupling guarantees:
  - This module imports only from app.config, app.db.base, app.storage.s3,
    app.modules.drive.keys, app.modules.ingest (for the write path),
    app.modules.search.scene_client, and its own engines package. No
    cross-feature imports.
  - The engines package has zero imports from anything in app/, so it
    remains extractable into a dedicated worker later.
  - The engine is constructed lazily on first use and cached for the
    lifetime of the process. Missing OpenAI API key raises at construction
    time, not at import time.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .engines.base import (
    BudgetExceededError,
    CaptionEngine,
    CaptionResult,
    PersonSafetyViolation,
    RetryableEngineError,
    TerminalEngineError,
)
from .engines.factory import build_image_caption_engine

logger = logging.getLogger(__name__)


# Strong-ref set so fire-and-forget tasks don't get GC'd mid-flight.
# See https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


# Lazy singleton — constructed on first schedule call, reused across requests.
_SERVICE_SINGLETON: "ImageCaptionService | None" = None
_SERVICE_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class SceneCaptionRequest:
    """What the router passes to schedule one scene's captioning.

    The router already has all of these fields from the IngestScenesRequest
    body it's processing, so we don't re-fetch from DB.
    """

    org_id: UUID
    video_id: str
    scene_id: str
    file_name: str | None = None
    library_name: str | None = None


class ImageCaptionService:
    """Orchestrates: S3 download → engine.caption → enrich_scenes.

    One instance per api process. Holds:
      - The OpenAI-backed CaptionEngine (sync, thread-safe)
      - A semaphore capping in-flight OpenAI calls (the engine has its own
        internal threading semaphore; this one is for async back-pressure)
    """

    def __init__(self, engine: CaptionEngine, max_concurrency: int) -> None:
        self._engine = engine
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def engine(self) -> CaptionEngine:
        return self._engine

    async def caption_scenes(self, requests: list[SceneCaptionRequest]) -> None:
        """Caption a batch of image scenes sequentially per scene but
        bounded by the semaphore across the process.

        Failures for one scene never block others.
        """

        for req in requests:
            async with self._semaphore:
                try:
                    await self._caption_one(req)
                except BudgetExceededError:
                    logger.warning(
                        "image_caption_budget_exhausted_pausing",
                        extra={
                            "org_id": str(req.org_id),
                            "video_id": req.video_id,
                            "scene_id": req.scene_id,
                        },
                    )
                    # Stop processing the rest of the batch — budget is
                    # process-wide, retrying the remaining scenes would
                    # just raise again. They stay at caption_status=pending
                    # for the backfill CLI to pick up later.
                    return
                except PersonSafetyViolation:
                    # Already logged inside the engine. Nothing to do here.
                    pass
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "image_caption_scene_failed",
                        extra={
                            "org_id": str(req.org_id),
                            "video_id": req.video_id,
                            "scene_id": req.scene_id,
                        },
                    )

    async def _caption_one(self, req: SceneCaptionRequest) -> None:
        from app.modules.drive.keys import enrichment_keyframe_s3_key

        org_id_str = str(req.org_id)
        s3_key = enrichment_keyframe_s3_key(org_id_str, req.video_id, req.scene_id)

        with tempfile.TemporaryDirectory(prefix=f"imgcap_{req.scene_id}_") as td:
            local_path = Path(td) / f"{req.scene_id}.jpg"

            try:
                await self._download_keyframe(s3_key, local_path)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "image_caption_keyframe_download_failed",
                    extra={
                        "org_id": org_id_str,
                        "video_id": req.video_id,
                        "scene_id": req.scene_id,
                        "s3_key": s3_key,
                        "error": f"{type(e).__name__}: {e}",
                    },
                )
                return

            # Engine is sync and uses its own threading semaphore / retries.
            # Offload to executor so the event loop isn't blocked for
            # 1-30 seconds per call.
            loop = asyncio.get_running_loop()
            hints = {
                "file_name": req.file_name or "",
                "library_name": req.library_name or "",
            }
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: self._engine.caption(local_path, hints=hints),
                )
            except (BudgetExceededError, PersonSafetyViolation):
                raise
            except (RetryableEngineError, TerminalEngineError) as e:
                logger.warning(
                    "image_caption_engine_error",
                    extra={
                        "org_id": org_id_str,
                        "video_id": req.video_id,
                        "scene_id": req.scene_id,
                        "error_type": type(e).__name__,
                        "error": str(e)[:500],
                    },
                )
                return

            if not result.caption or result.validation_failure is not None:
                # Already logged inside the engine (parse error or safety
                # violation). Nothing to write.
                return

            await self._write_caption(req, result)

    async def _download_keyframe(self, s3_key: str, local_path: Path) -> None:
        from app.config import get_settings
        from app.storage.s3 import S3Client

        settings = get_settings()
        s3 = S3Client(bucket=settings.drive_s3_bucket)
        await s3.download_file_async(s3_key, local_path)

    async def _write_caption(
        self,
        req: SceneCaptionRequest,
        result: CaptionResult,
    ) -> None:
        """Write caption through the existing enrich_scenes path and
        stamp drive_files with caption metadata.

        Uses a fresh AsyncSession — we're in a background task, not a
        request handler, so we cannot reuse the request-scoped session.

        Going through SceneIngestService.enrich_scenes() ensures the
        scene_overrides.protected check runs, preserving user-edited
        captions. We deliberately stamp drive_files.caption_status
        regardless of whether the override won, because the point of
        this column is "was this row considered by the current prompt
        version" — not "whose caption is in the index."
        """

        from datetime import datetime, timezone

        from sqlalchemy import update

        from app.db.base import get_async_session_factory
        from app.modules.drive.models import DriveFile
        from app.modules.ingest.schemas import (
            EnrichScenesRequest,
            EnrichSceneUpdate,
        )
        from app.modules.ingest.service import SceneIngestService
        from app.modules.search.scene_client import SceneSearchClient

        caption_text = result.caption[:5_000]

        enrich_request = EnrichScenesRequest(
            video_id=req.video_id,
            scenes=[
                EnrichSceneUpdate(
                    scene_id=req.scene_id,
                    scene_caption=caption_text,
                )
            ],
        )

        scene_client = SceneSearchClient()
        try:
            session_factory = get_async_session_factory()
            async with session_factory() as session:
                ingest_service = SceneIngestService(
                    session=session,
                    scene_opensearch=scene_client,
                )
                await ingest_service.enrich_scenes(
                    request=enrich_request,
                    org_id=req.org_id,
                )

                await session.execute(
                    update(DriveFile)
                    .where(
                        DriveFile.org_id == req.org_id,
                        DriveFile.video_id == req.video_id,
                    )
                    .values(
                        caption_status="done",
                        caption_error=None,
                        caption_engine=result.model,
                        caption_prompt_version=result.prompt_version,
                        caption_generated_at=datetime.now(timezone.utc),
                    )
                )

                await session.commit()

            logger.info(
                "image_caption_written",
                extra={
                    "org_id": str(req.org_id),
                    "video_id": req.video_id,
                    "scene_id": req.scene_id,
                    "caption_chars": len(caption_text),
                    "prompt_version": result.prompt_version,
                    "model": result.model,
                    "prompt_tokens": result.usage.prompt_tokens,
                    "cached_prompt_tokens": result.usage.cached_prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "latency_ms": result.latency_ms,
                },
            )
        finally:
            await scene_client.close()


async def get_service() -> "ImageCaptionService | None":
    """Return the process-wide singleton, constructing on first use.

    Returns None when image_caption_enabled is False — callers should
    short-circuit in that case. Construction is guarded by an asyncio
    lock so two concurrent first-users share the same instance.
    """

    global _SERVICE_SINGLETON
    if _SERVICE_SINGLETON is not None:
        return _SERVICE_SINGLETON

    async with _SERVICE_LOCK:
        if _SERVICE_SINGLETON is not None:
            return _SERVICE_SINGLETON

        from app.config import get_settings

        settings = get_settings()
        if not settings.image_caption_enabled:
            return None

        # Build engine. Raises if openai_api_key is missing.
        try:
            engine = build_image_caption_engine(settings)
        except Exception:
            logger.exception("image_caption_engine_build_failed")
            return None

        _SERVICE_SINGLETON = ImageCaptionService(
            engine=engine,
            max_concurrency=settings.image_caption_max_concurrency,
        )
        return _SERVICE_SINGLETON


def schedule_image_caption_task(
    scenes: list[SceneCaptionRequest],
) -> None:
    """Fire-and-forget scheduler. Safe to call from any async handler.

    The router hook calls this after the ingest response is computed.
    Captioning runs on the same event loop but outside the request's
    lifecycle — failures do not affect the HTTP response.

    No-op when:
      - `scenes` is empty
      - image_caption_enabled is False (checked inside get_service)
      - Engine construction failed (logged; returns None)
    """

    if not scenes:
        return

    async def _runner() -> None:
        try:
            service = await get_service()
            if service is None:
                return
            await service.caption_scenes(scenes)
        except Exception:  # noqa: BLE001
            logger.exception(
                "image_caption_background_runner_failed",
                extra={"scene_count": len(scenes)},
            )

    task = asyncio.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def reset_service_for_tests() -> None:
    """Reset the singleton so unit tests can swap in a stub engine."""

    global _SERVICE_SINGLETON
    _SERVICE_SINGLETON = None
