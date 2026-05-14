import asyncio
import logging
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.dependencies import get_scene_opensearch_client, get_shorts_render_service
from app.modules.auth.service import get_current_user
from app.modules.shorts_render.rate_limit import require_shorts_render_rate_limit
from app.modules.shorts_render.schemas import (
    RenderJobCreate,
    RenderJobListResponse,
    RenderJobResponse,
    RenderJobSubtitlesUpdate,
    RenderJobTitleUpdate,
    SubtitleSuggestion,
    SubtitleSuggestions,
    ShortsSummaryRequest,
    ShortsSummaryResponse,
)
from app.modules.shorts_render.service import ShortsRenderService
from app.modules.shorts_render.summary_service import (
    ShortsRenderSummaryService,
    SummaryError,
    SummaryNotReadyError,
    SummaryUnavailableError,
)
from app.modules.tenancy.context import OrgContext
from app.modules.tenancy.middleware import get_current_org
from app.modules.users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shorts/render", tags=["shorts-render"])

_RANGE_CHUNK = 2 * 1024 * 1024  # 2MB default for open-ended ranges


@router.post("", response_model=RenderJobResponse, status_code=status.HTTP_201_CREATED)
async def create_render_job(
    body: RenderJobCreate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
    _rate_limit: Annotated[None, Depends(require_shorts_render_rate_limit)] = None,
):
    user_id = cast(UUID, user.id)
    return await service.create_render_job(org_ctx.org_id, user_id, body)


@router.get("", response_model=RenderJobListResponse)
async def list_render_jobs(
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    user_id = cast(UUID, user.id)
    return await service.list_render_jobs(org_ctx.org_id, user_id, limit, offset)


@router.get("/{job_id}", response_model=RenderJobResponse)
async def get_render_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    user_id = cast(UUID, user.id)
    return await service.get_render_job(org_ctx.org_id, user_id, job_id)


@router.patch("/{job_id}", response_model=RenderJobResponse)
async def update_render_job_title(
    job_id: UUID,
    body: RenderJobTitleUpdate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    """Rename a render job. Owner-scoped — 404 when the caller doesn't own the job."""
    user_id = cast(UUID, user.id)
    return await service.update_render_job_title(
        org_ctx.org_id, user_id, job_id, body.title,
    )


@router.post(
    "/{job_id}/rerender",
    response_model=RenderJobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rerender_render_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
    _rate_limit: Annotated[None, Depends(require_shorts_render_rate_limit)] = None,
):
    """Promote a render's current ``input_spec`` to a fresh queued render.

    Pairs with the manual subtitle-edit flow:
      1. Operator edits subtitles in the wizard.
      2. Debounced PATCH ``/api/shorts/render/{id}/subtitles`` saves
         edits to ``parent.input_spec.subtitles``.
      3. Operator clicks "Render with my edits" → this endpoint.
      4. Backend creates a child render carrying the edited spec,
         links parent → child, enqueues to SQS.
      5. Frontend's ``useRefinedRenderChain`` swaps to the child
         once it completes.

    No body — the spec is whatever the parent's ``input_spec`` is at
    call time. This keeps "save" and "render" decoupled (auto-save
    is free; rendering is the explicit-cost action).

    Errors:
      - 404: render job not found OR not owned by the calling user.
      - 409: parent isn't in 'completed' status.
      - 429: per-user shorts-render rate limit hit.

    Idempotency: 30-second composition-hash dedupe window — repeated
    clicks return the existing child render rather than queueing
    duplicates.

    Plan: ``.claude/plans/auto-shorts-subtitle-editor-2026-05-06.md`` PR 1.
    """
    user_id = cast(UUID, user.id)
    return await service.rerender_from_edits(
        org_ctx.org_id, user_id, job_id,
    )


@router.patch("/{job_id}/subtitles", response_model=RenderJobResponse)
async def update_render_job_subtitles(
    job_id: UUID,
    body: RenderJobSubtitlesUpdate,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    """Replace the subtitles on a render job and lock out Whisper refinement.

    Sets ``refinement_source='manual_edit'`` on the row so the
    post-render Whisper hook (``post_render_hook.py`` in PR 4) skips
    refinement on this render. Manual edits stay sticky — even if the
    operator later clears all subtitles, the flag remains so a future
    Whisper pass doesn't repopulate them.

    Per CLAUDE.md "single-field schema; do NOT widen", this is a
    DEDICATED endpoint distinct from ``PATCH /api/shorts/render/{job_id}``
    (title only). New mutable fields should follow the same pattern
    rather than extending either body.

    Owner-scoped — 404 when the caller doesn't own the job. The
    response includes the updated subtitle count via the rebuilt
    ``input_spec`` and the new ``refinement_source`` value.
    """
    user_id = cast(UUID, user.id)
    return await service.update_render_job_subtitles(
        org_ctx.org_id, user_id, job_id, body.subtitles,
    )


_SUBTITLE_FILENAME_FALLBACK = "subtitles"
_SUBTITLE_MIME_BY_FORMAT = {
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
}


def _safe_subtitle_filename_stem(title: str | None) -> str:
    """Strip a job title down to a filesystem-friendly stem.

    Keeps Hangul, ASCII letters/digits, dash, underscore. Replaces
    other characters with ``-`` so operators get a recognisable
    filename instead of the render UUID. Falls back to
    ``_SUBTITLE_FILENAME_FALLBACK`` when the title is missing or
    sanitises to empty.
    """
    if not title:
        return _SUBTITLE_FILENAME_FALLBACK
    cleaned: list[str] = []
    for ch in title:
        if ch.isalnum() or ch == "_":
            cleaned.append(ch)
        elif "가" <= ch <= "힣":  # Hangul syllables
            cleaned.append(ch)
        else:
            # Any unsafe char becomes a dash; consecutive dashes are
            # collapsed below so "Heimdex Mini · {hash}" produces
            # "Heimdex-Mini-{hash}", not "Heimdex-Mini---{hash}".
            cleaned.append("-")
    stem = "".join(cleaned)
    while "--" in stem:
        stem = stem.replace("--", "-")
    stem = stem.strip("-")
    return stem or _SUBTITLE_FILENAME_FALLBACK


@router.get(
    "/{job_id}/subtitles.{fmt}",
    response_class=PlainTextResponse,
)
async def download_render_job_subtitles(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
    fmt: Annotated[str, Path(pattern="^(srt|vtt)$")],
):
    """Serialize the render's current ``input_spec.subtitles`` and return as a download.

    Reads from ``input_spec.subtitles`` (where PATCH ``/subtitles``
    persists operator edits), so the downloaded file always reflects
    the LATEST saved cues — not whatever was burned into the rendered
    MP4. Operators can edit + immediately download a polished
    subtitle file without waiting for a re-render.

    Owner-scoped — 404 when the caller doesn't own the job. Returns
    200 with an empty body when the job exists but carries zero
    subtitles (rare; image-only renders, legacy compositions). The
    SubtitleEditor's empty-state copy already handles "no cues" UX,
    so a 200-empty download keeps the contract simple.

    The ``Content-Disposition`` header sets a sensible default
    filename — uses the (sanitised) job title with the ``.srt`` /
    ``.vtt`` extension. Korean titles are preserved via the RFC 5987
    ``filename*`` form alongside an ASCII fallback for older
    clients.
    """
    from urllib.parse import quote

    from app.modules.shorts_render.subtitles_export import (
        subtitles_to_srt,
        subtitles_to_vtt,
    )

    user_id = cast(UUID, user.id)
    job = await service.get_render_job_record(org_ctx.org_id, user_id, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Render job not found",
        )

    subtitles = (job.input_spec or {}).get("subtitles") or []
    body = (
        subtitles_to_srt(subtitles)
        if fmt == "srt"
        else subtitles_to_vtt(subtitles)
    )

    stem = _safe_subtitle_filename_stem(job.title)
    filename = f"{stem}.{fmt}"
    ascii_filename = f"{_SUBTITLE_FILENAME_FALLBACK}.{fmt}"
    content_disposition = (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )

    return PlainTextResponse(
        content=body,
        media_type=_SUBTITLE_MIME_BY_FORMAT[fmt],
        headers={"Content-Disposition": content_disposition},
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_render_job(
    job_id: UUID,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    user_id = cast(UUID, user.id)
    await service.delete_render_job(org_ctx.org_id, user_id, job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{job_id}/download")
async def download_rendered_short(
    job_id: UUID,
    request: Request,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ShortsRenderService, Depends(get_shorts_render_service)],
):
    """Stream the rendered MP4 from S3. Supports HTTP Range requests."""
    user_id = cast(UUID, user.id)
    job = await service.get_render_job_record(org_ctx.org_id, user_id, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Render job not found")

    if job.status != "completed" or not job.output_s3_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Render job is not ready for download",
        )

    from app.config import get_settings
    from app.storage.s3 import S3Client

    settings = get_settings()
    s3 = S3Client(bucket=settings.drive_s3_bucket)

    try:
        loop = asyncio.get_running_loop()
        head = await loop.run_in_executor(
            None, lambda: s3._client.head_object(Bucket=s3.bucket, Key=job.output_s3_key)
        )
    except Exception:
        logger.warning("download_head_failed", extra={"key": job.output_s3_key}, exc_info=True)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to retrieve file from storage")

    total_size = head["ContentLength"]
    content_type = "video/mp4"
    filename = f"short_{job_id}.mp4"

    range_header = request.headers.get("range")

    if range_header:
        range_spec = range_header.strip().lower()
        if not range_spec.startswith("bytes="):
            raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE)

        range_val = range_spec[6:]
        parts = range_val.split("-", 1)
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else min(start + _RANGE_CHUNK - 1, total_size - 1)
        end = min(end, total_size - 1)

        if start >= total_size or start > end:
            raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE)

        content_length = end - start + 1
        s3_key = job.output_s3_key

        def _range_iter():
            resp = s3._client.get_object(
                Bucket=s3.bucket, Key=s3_key, Range=f"bytes={start}-{end}",
            )
            body = resp["Body"]
            try:
                while True:
                    chunk = body.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                body.close()

        return StreamingResponse(
            _range_iter(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{total_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, max-age=3600",
            },
        )

    s3_key = job.output_s3_key

    def _full_iter():
        resp = s3._client.get_object(Bucket=s3.bucket, Key=s3_key)
        body = resp["Body"]
        try:
            while True:
                chunk = body.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    return StreamingResponse(
        _full_iter(),
        media_type=content_type,
        headers={
            "Content-Length": str(total_size),
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


_TRANSCRIPT_MAX_LEN = 50


@router.get(
    "/suggestions/{video_id}/{scene_id}",
    response_model=SubtitleSuggestions,
)
async def get_subtitle_suggestions(
    video_id: str,
    scene_id: str,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)],
    user: Annotated[User, Depends(get_current_user)],
    scene_opensearch=Depends(get_scene_opensearch_client),
):
    """Return subtitle text suggestions from scene metadata."""
    doc_id = f"{org_ctx.org_id}:{scene_id}"
    scenes = await scene_opensearch.mget_scenes([doc_id])
    scene_doc = scenes.get(doc_id)

    if scene_doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scene not found: {scene_id}",
        )

    seen: set[str] = set()
    suggestions: list[SubtitleSuggestion] = []

    # Product tags first
    for tag in scene_doc.get("product_tags") or []:
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            suggestions.append(SubtitleSuggestion(text=tag, source="product_tag"))

    # Keyword tags second
    for tag in scene_doc.get("keyword_tags") or []:
        tag = tag.strip()
        if tag and tag not in seen:
            seen.add(tag)
            suggestions.append(SubtitleSuggestion(text=tag, source="keyword_tag"))

    # Transcript last (truncated)
    transcript = (scene_doc.get("transcript_raw") or "").strip()
    if transcript:
        truncated = transcript[:_TRANSCRIPT_MAX_LEN]
        if truncated not in seen:
            seen.add(truncated)
            suggestions.append(SubtitleSuggestion(text=truncated, source="transcript"))

    return SubtitleSuggestions(suggestions=suggestions)


@router.post(
    "/{job_id}/summary",
    response_model=ShortsSummaryResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_render_job_summary(
    job_id: UUID,
    body: ShortsSummaryRequest | None = None,
    org_ctx: Annotated[OrgContext, Depends(get_current_org)] = ...,
    user: Annotated[User, Depends(get_current_user)] = ...,
    service: Annotated[
        ShortsRenderService, Depends(get_shorts_render_service)
    ] = ...,
    os_client: Annotated[
        Any, Depends(get_scene_opensearch_client)
    ] = ...,
):
    """Generate a 1-2 sentence Korean summary for a completed render.

    Reuses existing scene signals (STT + scene_caption + OCR + speaker)
    from the source video. No frame extraction.
    """
    from app.config import get_settings
    from openai import AsyncOpenAI

    user_id = cast(UUID, user.id)
    settings = get_settings()

    if not settings.shorts_render_summary_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="shorts_render_summary disabled",
        )

    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="openai api key not configured",
        )

    # Owner-scoped fetch — 404 when not owned by caller
    render_job = await service.get_render_job_orm(
        org_ctx.org_id, user_id, job_id,
    )
    if render_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="render job not found",
        )

    max_sentences = body.max_sentences if body else 2

    summary_service = ShortsRenderSummaryService(
        openai_client=AsyncOpenAI(api_key=api_key),
        os_client=os_client,
        model=settings.shorts_render_summary_llm_model,
        timeout_s=settings.shorts_render_summary_llm_timeout_s,
        prompt_version=settings.shorts_render_summary_prompt_version,
    )

    try:
        result = await summary_service.generate(
            org_id=org_ctx.org_id,
            render_job=render_job,
            max_sentences=max_sentences,
        )
    except SummaryNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except SummaryUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except SummaryError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    return ShortsSummaryResponse(
        render_job_id=result.render_job_id,
        summary=result.summary,
        prompt_version=result.prompt_version,
        model=result.model,
        cost_usd=result.cost_usd,
        generated_at=result.generated_at,
    )