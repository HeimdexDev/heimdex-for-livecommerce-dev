import asyncio
import logging
import math
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db_session, get_reprocess_repository, get_scene_opensearch_client
from app.modules.search.scene_client import SceneSearchClient
from app.modules.videos.reprocess_repository import ReprocessRepository
from app.sqs_producer import (
    publish_enrichment_jobs,
    publish_scene_enrichment_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["videos-internal"])

from app.dependencies import verify_internal_token as _verify_internal_token


async def _publish_scene_jobs_in_background(
    *,
    file_id: UUID,
    org_id: UUID,
    video_id: str,
    scenes: list[dict[str, Any]],
) -> None:
    """Publish per-scene SQS messages in a background thread.

    Runs ``publish_scene_enrichment_jobs`` via ``run_in_executor`` so the
    synchronous boto3 ``send_message_batch`` calls don't block the event loop.
    Called from ``asyncio.create_task()`` after the PATCH response is sent.
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: publish_scene_enrichment_jobs(
                file_id=file_id,
                org_id=org_id,
                video_id=video_id,
                scenes=scenes,
            ),
        )
        logger.info(
            "reprocess_scene_enrichment_jobs_published",
            extra={"video_id": video_id, "scene_count": len(scenes)},
        )
    except Exception:
        logger.warning(
            "reprocess_scene_enrichment_jobs_failed",
            extra={"video_id": video_id, "scene_count": len(scenes)},
            exc_info=True,
        )


@router.delete("/{video_id}/scenes")
async def delete_video_scenes(
    video_id: str,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    deleted = await scene_client.delete_scenes_by_video_id(str(org_id), video_id)
    return {"deleted": deleted}


@router.patch("/{video_id}/reprocess/{job_id}/status")
async def update_reprocess_status(
    video_id: str,
    job_id: str,
    status_value: str = Body(..., alias="status"),
    scene_count: int | None = Body(None),
    error: str | None = Body(None),
    org_id: str | None = Body(None),
    keyframe_s3_prefix: str | None = Body(None),
    audio_s3_key: str | None = Body(None),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    repo: ReprocessRepository = Depends(get_reprocess_repository),
):
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format",
        )

    await repo.update_status(
        parsed_job_id,
        status_value,
        scene_count=scene_count,
        error=error,
    )

    # Publish enrichment SQS jobs when resplit completes successfully.
    # Mirrors the pattern in internal_processing_router.py and
    # youtube/internal_router.py — enrichment fires as a side effect
    # of status transitioning to 'completed'.
    if (
        status_value == "completed"
        and scene_count
        and scene_count > 0
        and org_id
        and keyframe_s3_prefix
    ):
        file_uuid = await _resolve_file_id(db, video_id, UUID(org_id))
        if file_uuid is not None:
            parsed_org_id = UUID(org_id)

            # v1: per-video enrichment for STT, OCR, face
            publish_enrichment_jobs(
                file_id=file_uuid,
                org_id=parsed_org_id,
                video_id=video_id,
                keyframe_s3_prefix=keyframe_s3_prefix,
                audio_s3_key=audio_s3_key,
            )

            # v2: per-scene enrichment for caption + visual-embed
            scenes_for_publish = [
                {
                    "scene_id": f"{video_id}_scene_{i:03d}",
                    "scene_index": i,
                    "keyframe_s3_key": f"{keyframe_s3_prefix}{video_id}_scene_{i:03d}.jpg",
                }
                for i in range(scene_count)
            ]
            asyncio.create_task(
                _publish_scene_jobs_in_background(
                    file_id=file_uuid,
                    org_id=parsed_org_id,
                    video_id=video_id,
                    scenes=scenes_for_publish,
                )
            )

            logger.info(
                "reprocess_enrichment_published",
                extra={
                    "video_id": video_id,
                    "job_id": job_id,
                    "scene_count": scene_count,
                    "file_id": str(file_uuid),
                },
            )

    return {"status": "ok"}


@router.get("/{file_id}/scenes-with-keyframes")
async def get_scenes_with_keyframes(
    file_id: UUID,
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    """Phase 2.5a — internal lookup for the shorts-auto product mode v2
    workers (enumerate + track).

    Resolves a ``DriveFile`` UUID into the chronologically-ordered list
    of scenes for that video, augmented with the keyframe S3 key
    (constructed via the canonical ``enrichment_keyframe_s3_key``
    helper). Both new product workers consume this; keeping the join
    server-side avoids each worker re-implementing the
    ``DriveFile`` → string ``video_id`` translation + key construction
    independently (drift between them would silently produce 404s on
    the worker side).

    Bearer-authed via the shared internal token. Org context comes
    from the ``X-Heimdex-Org-Id`` header — same pattern as the other
    internal endpoints in this file. Cross-org access returns 404
    (no info leak between not-found and forbidden).

    Response shape (stable; both workers depend on it)::

        {
          "video_id": "gd_<...>",        # string id used by OS
          "drive_file_id": "<uuid>",
          "total_duration_ms": <int>,    # max(end_ms) across scenes
          "scenes": [
            {
              "scene_id": "gd_<...>_scene_007",
              "start_ms": <int>,
              "end_ms": <int>,
              "keyframe_timestamp_ms": <int|null>,
              "keyframe_s3_key": "<org>/drive/keyframes/<video>/<scene>.jpg"
            },
            ...
          ]
        }
    """
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    from app.modules.drive.keys import enrichment_keyframe_s3_key
    from app.modules.drive.repository import DriveFileRepository

    # Resolve DriveFile (org-scoped — cross-org access returns 404).
    drive_file = await DriveFileRepository(db).get_by_id(
        file_id=file_id, org_id=org_id,
    )
    if drive_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="video not found",
        )
    video_id_str: str = drive_file.video_id

    # Pull all scenes for this video. ``page_size`` is generous —
    # 500 covers > 99% of livecommerce videos (45s default split,
    # ~4hr cap → ~320 scenes). Bumping to 5000 if a longer video
    # surfaces.
    response = await scene_client.get_video_scenes(
        org_id=str(org_id),
        video_id=video_id_str,
        page_size=500,
        offset=0,
    )
    raw_scenes = response.get("scenes", [])

    enriched: list[dict[str, Any]] = []
    total_duration_ms = 0
    for scene in raw_scenes:
        scene_id = scene.get("scene_id")
        if not scene_id:
            # Defensive: drop malformed rows rather than 500 the worker.
            continue
        start_ms = int(scene.get("start_ms", 0))
        end_ms = int(scene.get("end_ms", 0))
        total_duration_ms = max(total_duration_ms, end_ms)
        kf_ts = scene.get("keyframe_timestamp_ms")
        enriched.append({
            "scene_id": scene_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "keyframe_timestamp_ms": (
                int(kf_ts) if kf_ts is not None else None
            ),
            # Canonical key — same helper drive-worker uses when it
            # wrote the keyframe. Drift-proof by construction.
            "keyframe_s3_key": enrichment_keyframe_s3_key(
                str(org_id), video_id_str, scene_id,
            ),
        })

    # Defensive ordering — ``get_video_scenes`` already sorts by
    # start_ms ascending when no query is supplied, but a downstream
    # change there shouldn't silently break the worker's chronological
    # iteration assumption.
    enriched.sort(key=lambda s: s["start_ms"])

    return {
        "video_id": video_id_str,
        "drive_file_id": str(file_id),
        "total_duration_ms": total_duration_ms,
        "scenes": enriched,
    }


@router.post("/{file_id}/scenes-by-visual-similarity")
async def scenes_by_visual_similarity(
    file_id: UUID,
    body: dict[str, Any] = Body(...),
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    """Phase 3b — OpenSearch coarse pre-filter for the
    ``shorts-auto-product`` track worker.

    Given a 768-dim SigLIP2 embedding of the canonical product crop,
    return the top-K scenes from the same video ranked by cosine
    similarity to that vector. The track worker then locally
    re-embeds each candidate's keyframe for a precise pass before
    handing off to SAM2.

    Pre-filter is **per-video** (not per-org) — the canonical crop is
    derived from one specific video, so cross-video matches don't
    apply at v1. Cross-video product matching is v2 (per locked
    decisions in shorts-auto-product-v2 plan).

    Body shape::

        {
          "query_vec": [768 floats; SigLIP2 base/256 L2-normalized],
          "top_k": int (1..200),
          "min_similarity": float (0..1) — drops sub-threshold hits
                                            BEFORE returning so the
                                            worker doesn't have to.
        }

    Response shape::

        {
          "video_id": "gd_<...>",
          "scenes": [
            {"scene_id": "gd_<...>_scene_007", "similarity": 0.81},
            ...
          ]
        }

    Bearer-authed via the shared internal token. Org context comes
    from the ``X-Heimdex-Org-Id`` header. Cross-org access returns
    404 (no info leak).
    """
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    query_vec = body.get("query_vec")
    if not isinstance(query_vec, list) or not query_vec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="query_vec must be a non-empty list of floats",
        )
    if len(query_vec) != scene_client.VISUAL_EMBEDDING_DIMENSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"query_vec length {len(query_vec)} does not match the "
                f"deployed visual embedding dimension "
                f"{scene_client.VISUAL_EMBEDDING_DIMENSION} "
                f"(SigLIP2 base/256 — drift between worker and api "
                f"would silently produce nonsense rankings)"
            ),
        )
    # Per-element validation. Length-only validation lets payloads
    # with strings, booleans, or non-finite floats (NaN/inf) reach
    # OpenSearch unchanged — best case 500s on serialization, worst
    # case 200 with undefined ranking. ``bool`` is a subclass of
    # ``int`` in Python so we exclude it explicitly.
    for i, val in enumerate(query_vec):
        if (
            isinstance(val, bool)
            or not isinstance(val, (int, float))
            or not math.isfinite(val)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"query_vec[{i}] must be a finite number "
                    f"(got {type(val).__name__}={val!r})"
                ),
            )

    try:
        top_k = int(body.get("top_k", 60))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="top_k must be an int",
        )
    if top_k < 1 or top_k > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="top_k must be in [1, 200]",
        )

    try:
        min_similarity = float(body.get("min_similarity", 0.0))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_similarity must be a float",
        )
    if min_similarity < 0.0 or min_similarity > 1.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_similarity must be in [0, 1]",
        )

    from app.modules.drive.repository import DriveFileRepository

    drive_file = await DriveFileRepository(db).get_by_id(
        file_id=file_id, org_id=org_id,
    )
    if drive_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="video not found",
        )

    hits = await scene_client.search_visual_vector_in_video(
        visual_embedding=query_vec,
        org_id=str(org_id),
        video_id=drive_file.video_id,
        size=top_k,
    )

    scenes: list[dict[str, Any]] = []
    for hit in hits:
        score = float(hit.get("_score", 0.0))
        if score < min_similarity:
            continue
        source = hit.get("_source", {}) or {}
        scene_id = source.get("scene_id")
        if not scene_id:
            # Defensive — every doc should have a scene_id field;
            # skip silently rather than 500 the worker.
            continue
        scenes.append({"scene_id": scene_id, "similarity": score})

    return {"video_id": drive_file.video_id, "scenes": scenes}


@router.post("/{file_id}/scenes-content")
async def scenes_content(
    file_id: UUID,
    body: dict[str, Any] = Body(...),
    x_heimdex_org_id: str = Header(..., alias="X-Heimdex-Org-Id"),
    _token: str = Depends(_verify_internal_token),
    db: AsyncSession = Depends(get_db_session),
    scene_client: SceneSearchClient = Depends(get_scene_opensearch_client),
):
    """Phase 3b — bulk fetch transcripts + OCR for a list of
    scene_ids.

    The product track worker calls this AFTER the coarse pre-filter
    has narrowed candidates to ~5-10 scenes. Pulling transcripts +
    OCR for those scenes lets the alignment lib annotate windows
    with ``has_narration_mention`` + ``has_ocr_overlap``.

    Returning per-scene scope rather than per-utterance is intentional:
    OpenSearch scene docs store transcript_raw / ocr_text_raw as full
    strings without per-utterance temporal bounds. The alignment lib
    treats segments without bounds as covering the whole scene
    (correct for the v1 product track use case where windows are
    always within scene bounds anyway).

    Body shape::

        {
          "scene_ids": ["gd_<...>_scene_007", "gd_<...>_scene_012", ...]
        }

    Response shape::

        {
          "video_id": "gd_<...>",
          "scenes": [
            {
              "scene_id": "gd_<...>_scene_007",
              "start_ms": 5000,
              "end_ms": 10000,
              "transcript_raw": "...",
              "speaker_transcript": "...",
              "ocr_text_raw": "..."
            },
            ...
          ]
        }

    Cross-org / cross-video doc IDs are silently dropped (the
    constructed doc_id is org-scoped via the ``{org_id}:{scene_id}``
    prefix, so a scene_id from another org just doesn't match).
    """
    try:
        org_id = UUID(x_heimdex_org_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid X-Heimdex-Org-Id: {x_heimdex_org_id!r}",
        )

    scene_ids = body.get("scene_ids")
    if not isinstance(scene_ids, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scene_ids must be a list",
        )
    if len(scene_ids) > 200:
        # Same per-call cap as the existing scenes-with-keyframes
        # endpoint's page_size — protects OS from a worker requesting
        # tens of thousands of scenes in one call.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scene_ids may not exceed 200 entries per call",
        )
    if not all(isinstance(s, str) and s for s in scene_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scene_ids must be a list of non-empty strings",
        )

    from app.modules.drive.repository import DriveFileRepository

    drive_file = await DriveFileRepository(db).get_by_id(
        file_id=file_id, org_id=org_id,
    )
    if drive_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="video not found",
        )

    # Build the org-scoped doc_ids the OS index uses.
    doc_ids = [f"{org_id}:{scene_id}" for scene_id in scene_ids]
    raw = await scene_client.mget_scenes(doc_ids)

    out: list[dict[str, Any]] = []
    for scene_id in scene_ids:
        doc_id = f"{org_id}:{scene_id}"
        source = raw.get(doc_id)
        if source is None:
            # Scene not found (cross-org / typo / deleted) — skip.
            continue
        # Defense in depth: the doc_id prefix already org-scopes, but
        # also check the scene actually belongs to the requested
        # video so a typo'd scene_id from another video on the same
        # org doesn't leak.
        if source.get("video_id") != drive_file.video_id:
            continue
        out.append({
            "scene_id": source.get("scene_id", scene_id),
            "start_ms": int(source.get("start_ms", 0) or 0),
            "end_ms": int(source.get("end_ms", 0) or 0),
            "transcript_raw": source.get("transcript_raw") or "",
            "speaker_transcript": source.get("speaker_transcript") or "",
            "ocr_text_raw": source.get("ocr_text_raw") or "",
        })

    return {"video_id": drive_file.video_id, "scenes": out}


async def _resolve_file_id(
    db: AsyncSession, video_id: str, org_id: UUID,
) -> UUID | None:
    """Look up the real DriveFile or YouTubeVideo UUID for enrichment tracking.

    Enrichment workers use this UUID to report per-file enrichment status.
    Kept as a separate function to avoid coupling the status handler to
    repository internals.
    """
    if video_id.startswith("gd_"):
        from app.modules.drive.repository import DriveFileRepository
        repo = DriveFileRepository(db)
        drive_file = await repo.get_by_video_id(org_id, video_id)
        return drive_file.id if drive_file else None
    elif video_id.startswith("yt_"):
        from app.modules.youtube.repository import YouTubeVideoRepository
        repo = YouTubeVideoRepository(db)
        yt_video = await repo.get_by_video_id(org_id, video_id)
        return yt_video.id if yt_video else None
    return None
