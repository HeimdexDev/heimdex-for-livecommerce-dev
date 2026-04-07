import json
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.scene_overrides.models import SceneOverride

# Fields that users are allowed to override
EDITABLE_FIELDS = {"scene_caption", "transcript_raw", "speaker_transcript", "ai_tags"}

# Mapping from editable field name to model column names (override + original)
_FIELD_TO_COLUMN = {
    "scene_caption": ("scene_caption", "original_scene_caption"),
    "transcript_raw": ("transcript_raw", "original_transcript_raw"),
    "speaker_transcript": ("speaker_transcript", "original_speaker_transcript"),
    "ai_tags": ("ai_tags_json", "original_ai_tags_json"),
}


class SceneOverrideRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_scene(self, org_id: UUID, scene_id: str) -> SceneOverride | None:
        result = await self.session.execute(
            select(SceneOverride).where(
                SceneOverride.org_id == org_id,
                SceneOverride.scene_id == scene_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_video(self, org_id: UUID, video_id: str) -> list[SceneOverride]:
        result = await self.session.execute(
            select(SceneOverride).where(
                SceneOverride.org_id == org_id,
                SceneOverride.video_id == video_id,
            )
        )
        return list(result.scalars().all())

    async def get_overridden_fields(
        self, org_id: UUID, scene_ids: list[str]
    ) -> dict[str, set[str]]:
        """Batch lookup for worker protection.

        Returns {scene_id: {"scene_caption", "transcript_raw", ...}} for scenes
        that have user overrides.
        """
        if not scene_ids:
            return {}
        result = await self.session.execute(
            select(SceneOverride.scene_id, SceneOverride.overridden_fields).where(
                SceneOverride.org_id == org_id,
                SceneOverride.scene_id.in_(scene_ids),
            )
        )
        out: dict[str, set[str]] = {}
        for scene_id, fields_str in result.all():
            if fields_str:
                out[scene_id] = set(fields_str.split(","))
        return out

    async def upsert(
        self,
        org_id: UUID,
        scene_id: str,
        video_id: str,
        edited_by: UUID,
        fields: dict[str, str | list[str]],
        originals: dict[str, str | list[str] | None],
    ) -> SceneOverride:
        """Create or update override for a scene.

        Args:
            fields: {field_name: new_value} for fields being overridden.
            originals: {field_name: current_worker_value} captured from OpenSearch
                       before the override. Only used on first override of each field.
        """
        existing = await self.get_by_scene(org_id, scene_id)

        if existing:
            current_fields = set(existing.overridden_fields.split(",")) if existing.overridden_fields else set()
            for field_name, value in fields.items():
                if field_name not in EDITABLE_FIELDS:
                    continue
                col, orig_col = _FIELD_TO_COLUMN[field_name]
                stored = json.dumps(value, ensure_ascii=False) if field_name == "ai_tags" else value
                setattr(existing, col, stored)
                # Capture original only on first override of this field
                if field_name not in current_fields:
                    orig_val = originals.get(field_name)
                    orig_stored = json.dumps(orig_val, ensure_ascii=False) if field_name == "ai_tags" and orig_val is not None else orig_val
                    setattr(existing, orig_col, orig_stored)
                current_fields.add(field_name)
            existing.overridden_fields = ",".join(sorted(current_fields))
            existing.edited_by = edited_by
            await self.session.flush()
            return existing

        override = SceneOverride(
            org_id=org_id,
            scene_id=scene_id,
            video_id=video_id,
            edited_by=edited_by,
        )
        field_names: set[str] = set()
        for field_name, value in fields.items():
            if field_name not in EDITABLE_FIELDS:
                continue
            col, orig_col = _FIELD_TO_COLUMN[field_name]
            stored = json.dumps(value, ensure_ascii=False) if field_name == "ai_tags" else value
            setattr(override, col, stored)
            orig_val = originals.get(field_name)
            orig_stored = json.dumps(orig_val, ensure_ascii=False) if field_name == "ai_tags" and orig_val is not None else orig_val
            setattr(override, orig_col, orig_stored)
            field_names.add(field_name)
        override.overridden_fields = ",".join(sorted(field_names))

        self.session.add(override)
        await self.session.flush()
        return override

    async def reset_field(
        self, org_id: UUID, scene_id: str, field_name: str
    ) -> str | list[str] | None:
        """Remove a single field override and return the original worker value.

        Deletes the row entirely if no overridden fields remain.
        Returns the original value to write back to OpenSearch.
        """
        if field_name not in EDITABLE_FIELDS:
            return None

        existing = await self.get_by_scene(org_id, scene_id)
        if not existing:
            return None

        current_fields = set(existing.overridden_fields.split(",")) if existing.overridden_fields else set()
        if field_name not in current_fields:
            return None

        col, orig_col = _FIELD_TO_COLUMN[field_name]
        original_value = getattr(existing, orig_col)

        # Parse JSON for ai_tags
        if field_name == "ai_tags" and original_value is not None:
            original_value = json.loads(original_value)

        # Clear the override
        setattr(existing, col, None)
        current_fields.discard(field_name)

        if not current_fields:
            await self.session.delete(existing)
        else:
            existing.overridden_fields = ",".join(sorted(current_fields))
            setattr(existing, col, None)

        await self.session.flush()
        return original_value

    async def delete_by_video(self, org_id: UUID, video_id: str) -> int:
        """Delete all overrides for a video. Returns count of deleted rows."""
        result = await self.session.execute(
            delete(SceneOverride).where(
                SceneOverride.org_id == org_id,
                SceneOverride.video_id == video_id,
            )
        )
        await self.session.flush()
        return result.rowcount
