import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.dependencies import get_scene_opensearch_client
from app.logging_config import get_logger
from app.modules.auth import get_current_user
from app.modules.ingest.service import build_embedding_text
from app.modules.scene_overrides.repository import SceneOverrideRepository
from app.modules.scene_overrides.schemas import EDITABLE_FIELDS, SceneOverrideRequest, SceneOverrideResponse
from app.modules.search.embedding import get_passage_embeddings_batch
from app.modules.search.normalize import normalize_transcript
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.users.models import User

logger = get_logger(__name__)

router = APIRouter(
    prefix="/videos/{video_id}/scenes/{scene_id}",
    tags=["scene-overrides"],
)

# Text fields that affect the E5 search embedding
_TEXT_FIELDS = {"scene_caption", "transcript_raw", "speaker_transcript"}


def _build_opensearch_partial(
    field_name: str,
    value: str | list[str],
) -> dict:
    """Build the OpenSearch partial update dict for a single field."""
    if field_name == "scene_caption":
        norm = normalize_transcript(value)
        return {"scene_caption": norm}
    if field_name == "transcript_raw":
        norm = normalize_transcript(value)
        return {
            "transcript_raw": value,
            "transcript_norm": norm,
            "transcript_char_count": len(norm),
        }
    if field_name == "speaker_transcript":
        return {"speaker_transcript": value}
    if field_name == "ai_tags":
        return {"ai_tags": value}
    return {}


@router.patch("/override", response_model=SceneOverrideResponse)
async def patch_scene_override(
    video_id: str,
    scene_id: str,
    body: SceneOverrideRequest,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    org_id = org_ctx.org_id
    doc_id = f"{org_id}:{scene_id}"

    # Validate scene exists in OpenSearch
    existing_docs = await scene_opensearch.mget_scenes([doc_id])
    existing = existing_docs.get(doc_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scene not found")

    # Collect non-None fields from request
    fields: dict[str, str | list[str]] = {}
    if body.scene_caption is not None:
        fields["scene_caption"] = body.scene_caption
    if body.transcript_raw is not None:
        fields["transcript_raw"] = body.transcript_raw
    if body.speaker_transcript is not None:
        fields["speaker_transcript"] = body.speaker_transcript
    if body.ai_tags is not None:
        fields["ai_tags"] = body.ai_tags

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to override")

    # Capture current worker values as originals (for first-time overrides)
    originals: dict[str, str | list[str] | None] = {}
    for field_name in fields:
        if field_name == "ai_tags":
            originals[field_name] = existing.get("ai_tags", [])
        else:
            originals[field_name] = existing.get(field_name, "")

    # Upsert in PostgreSQL
    repo = SceneOverrideRepository(db)
    override = await repo.upsert(
        org_id=org_id,
        scene_id=scene_id,
        video_id=video_id,
        edited_by=user.id,
        fields=fields,
        originals=originals,
    )

    # Eagerly capture response data before any thread calls
    # (flush() expires ORM attributes; accessing them later in sync context crashes)
    response_fields = override.overridden_fields.split(",") if override.overridden_fields else []
    response_updated_at = override.updated_at.isoformat()

    # Dual-write to OpenSearch
    partial: dict = {}
    for field_name, value in fields.items():
        partial.update(_build_opensearch_partial(field_name, value))

    # Re-generate E5 embedding if text fields changed
    if fields.keys() & _TEXT_FIELDS:
        # Build effective text: use override value if overridden, else existing
        caption = normalize_transcript(fields.get("scene_caption", existing.get("scene_caption", "")))
        transcript = normalize_transcript(fields.get("transcript_raw", existing.get("transcript_raw", "")))
        ocr = existing.get("ocr_text_norm", "")
        embedding_text = build_embedding_text(transcript, ocr, caption)
        if embedding_text:
            vectors = await asyncio.to_thread(get_passage_embeddings_batch, [embedding_text])
            if vectors:
                partial["embedding_vector"] = vectors[0]

    if partial:
        await scene_opensearch.bulk_partial_update_scenes([(doc_id, partial)])

    logger.info(
        "scene_override_applied",
        org_id=str(org_id),
        scene_id=scene_id,
        fields=list(fields.keys()),
        user_id=str(user.id),
    )

    return SceneOverrideResponse(
        scene_id=scene_id,
        overridden_fields=response_fields,
        updated_at=response_updated_at,
    )


@router.delete("/override/{field_name}", status_code=200)
async def reset_scene_override(
    video_id: str,
    scene_id: str,
    field_name: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    if field_name not in EDITABLE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Field '{field_name}' is not editable")

    org_id = org_ctx.org_id
    doc_id = f"{org_id}:{scene_id}"

    repo = SceneOverrideRepository(db)
    original_value = await repo.reset_field(org_id, scene_id, field_name)

    if original_value is None and field_name != "ai_tags":
        raise HTTPException(status_code=404, detail="No override found for this field")

    # Write original value back to OpenSearch
    partial: dict = {}
    if original_value is not None:
        partial.update(_build_opensearch_partial(field_name, original_value))
    else:
        # No original stored — clear the field
        if field_name == "ai_tags":
            partial["ai_tags"] = []
        else:
            partial[field_name] = ""

    # Re-generate embedding with restored value
    if field_name in _TEXT_FIELDS:
        existing_docs = await scene_opensearch.mget_scenes([doc_id])
        existing = existing_docs.get(doc_id, {})
        # After reset, the effective value is the original (restored) value
        effective = dict(existing)
        if field_name == "scene_caption":
            effective["scene_caption"] = original_value or ""
        elif field_name == "transcript_raw":
            effective["transcript_raw"] = original_value or ""

        caption = normalize_transcript(effective.get("scene_caption", ""))
        transcript = normalize_transcript(effective.get("transcript_raw", ""))
        ocr = effective.get("ocr_text_norm", "")
        embedding_text = build_embedding_text(transcript, ocr, caption)
        if embedding_text:
            vectors = await asyncio.to_thread(get_passage_embeddings_batch, [embedding_text])
            if vectors:
                partial["embedding_vector"] = vectors[0]

    if partial:
        await scene_opensearch.bulk_partial_update_scenes([(doc_id, partial)])

    logger.info(
        "scene_override_reset",
        org_id=str(org_id),
        scene_id=scene_id,
        field=field_name,
        user_id=str(user.id),
    )

    return {"status": "reset", "field": field_name}


@router.get("/override", response_model=SceneOverrideResponse | None)
async def get_scene_override(
    video_id: str,
    scene_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    repo = SceneOverrideRepository(db)
    override = await repo.get_by_scene(org_ctx.org_id, scene_id)
    if not override:
        return None

    return SceneOverrideResponse(
        scene_id=scene_id,
        overridden_fields=override.overridden_fields.split(",") if override.overridden_fields else [],
        updated_at=override.updated_at.isoformat(),
    )
