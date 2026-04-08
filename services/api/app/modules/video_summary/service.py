"""Video summary orchestration: collect captions -> call LLM -> store."""

from __future__ import annotations

from uuid import UUID

from openai import AsyncOpenAI

from app.logging_config import get_logger
from app.modules.video_summary.openai_client import compute_input_hash, generate_video_summary
from app.modules.video_summary.prompts import CURRENT_VERSION, get_prompt
from app.modules.video_summary.repository import VideoSummaryRepository
from app.modules.video_summary.schemas import VideoSummaryResponse

logger = get_logger(__name__)

MAX_SCENES_FOR_SUMMARY = 50
MIN_CAPTIONS_FOR_SUMMARY = 2


class VideoSummaryService:
    def __init__(
        self,
        repo: VideoSummaryRepository,
        scene_client,  # SceneSearchClient — injected, not imported
        openai_client: AsyncOpenAI,
        model: str = "gpt-4o-mini",
    ) -> None:
        self._repo = repo
        self._scene_client = scene_client
        self._openai = openai_client
        self._model = model

    async def get_summary(self, org_id: UUID, video_id: str) -> VideoSummaryResponse | None:
        record = await self._repo.get_by_video(org_id, video_id)
        if record is None:
            return None

        captions = await self._fetch_captions(str(org_id), video_id)
        current_hash = compute_input_hash(captions) if captions else ""
        is_stale = bool(record.input_hash and current_hash and record.input_hash != current_hash)

        return VideoSummaryResponse(
            video_id=video_id,
            summary=record.effective_summary,
            is_edited=record.is_edited,
            is_stale=is_stale,
            model=record.model,
            prompt_version=record.prompt_version,
            scene_count=record.scene_count,
            generated_at=record.created_at,
            edited_at=record.edited_at,
        )

    async def generate(
        self,
        org_id: UUID,
        video_id: str,
        force: bool = False,
    ) -> VideoSummaryResponse:
        captions = await self._fetch_captions(str(org_id), video_id)
        video_title = await self._fetch_video_title(str(org_id), video_id)

        if len(captions) < MIN_CAPTIONS_FOR_SUMMARY:
            logger.info(
                "video_summary_skip_insufficient_captions",
                video_id=video_id,
                caption_count=len(captions),
            )
            return VideoSummaryResponse(
                video_id=video_id,
                summary="",
                scene_count=len(captions),
            )

        input_hash = compute_input_hash(captions)

        if not force:
            existing = await self._repo.get_by_video(org_id, video_id)
            if existing is not None and existing.input_hash == input_hash:
                logger.info("video_summary_cache_hit", video_id=video_id)
                return VideoSummaryResponse(
                    video_id=video_id,
                    summary=existing.effective_summary,
                    is_edited=existing.is_edited,
                    is_stale=False,
                    model=existing.model,
                    prompt_version=existing.prompt_version,
                    scene_count=existing.scene_count,
                    generated_at=existing.created_at,
                    edited_at=existing.edited_at,
                )

        prompt = get_prompt(CURRENT_VERSION)
        truncated = captions[:MAX_SCENES_FOR_SUMMARY]

        logger.info(
            "video_summary_generating",
            video_id=video_id,
            model=self._model,
            caption_count=len(truncated),
        )

        summary_text = await generate_video_summary(
            client=self._openai,
            video_title=video_title,
            scene_captions=truncated,
            system_prompt=prompt.system,
            user_template=prompt.user_template,
            model=self._model,
            max_tokens=300,
        )

        record = await self._repo.upsert(
            org_id=org_id,
            video_id=video_id,
            summary=summary_text,
            model=self._model,
            prompt_version=CURRENT_VERSION,
            scene_count=len(truncated),
            input_hash=input_hash,
        )

        await self._denormalize_to_opensearch(str(org_id), video_id, record.effective_summary)

        logger.info(
            "video_summary_generated",
            video_id=video_id,
            summary_length=len(summary_text),
        )

        return VideoSummaryResponse(
            video_id=video_id,
            summary=record.effective_summary,
            is_edited=record.is_edited,
            is_stale=False,
            model=record.model,
            prompt_version=record.prompt_version,
            scene_count=record.scene_count,
            generated_at=record.created_at,
            edited_at=record.edited_at,
        )

    async def edit_summary(
        self,
        org_id: UUID,
        video_id: str,
        override_text: str,
        user_id: UUID,
    ) -> VideoSummaryResponse | None:
        record = await self._repo.set_override(org_id, video_id, override_text, user_id)
        if record is None:
            return None

        await self._denormalize_to_opensearch(str(org_id), video_id, record.effective_summary)

        return VideoSummaryResponse(
            video_id=video_id,
            summary=record.effective_summary,
            is_edited=True,
            is_stale=False,
            model=record.model,
            prompt_version=record.prompt_version,
            scene_count=record.scene_count,
            generated_at=record.created_at,
            edited_at=record.edited_at,
        )

    async def reset_summary(
        self,
        org_id: UUID,
        video_id: str,
    ) -> VideoSummaryResponse | None:
        record = await self._repo.clear_override(org_id, video_id)
        if record is None:
            return None

        await self._denormalize_to_opensearch(str(org_id), video_id, record.effective_summary)

        return VideoSummaryResponse(
            video_id=video_id,
            summary=record.effective_summary,
            is_edited=False,
            is_stale=False,
            model=record.model,
            prompt_version=record.prompt_version,
            scene_count=record.scene_count,
            generated_at=record.created_at,
            edited_at=record.edited_at,
        )

    async def _fetch_captions(self, org_id: str, video_id: str) -> list[str]:
        scenes = await self._scene_client.get_video_scenes(org_id, video_id)
        captions = []
        for scene in scenes:
            src = scene.get("_source", {}) if isinstance(scene, dict) else {}
            cap = src.get("scene_caption", "").strip()
            if cap:
                captions.append(cap)
        return captions

    async def _fetch_video_title(self, org_id: str, video_id: str) -> str:
        scenes = await self._scene_client.get_video_scenes(org_id, video_id)
        if scenes:
            src = scenes[0].get("_source", {}) if isinstance(scenes[0], dict) else {}
            return src.get("video_title", "")
        return ""

    async def _denormalize_to_opensearch(
        self, org_id: str, video_id: str, summary_text: str,
    ) -> None:
        scene_ids = await self._scene_client.find_scene_ids_by_video_id(org_id, video_id)
        if not scene_ids:
            return

        doc_ids = [f"{org_id}:{sid}" for sid in scene_ids]
        actions: list[dict] = []
        for doc_id in doc_ids:
            actions.append({"update": {"_index": self._scene_client.alias_name, "_id": doc_id}})
            actions.append({"doc": {"video_summary": summary_text}})

        if actions:
            await self._scene_client.client.bulk(body=actions)
            logger.debug(
                "video_summary_denormalized",
                video_id=video_id,
                scene_count=len(doc_ids),
            )
