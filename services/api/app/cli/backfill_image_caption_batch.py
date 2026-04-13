"""Backfill image captions via OpenAI's Batch API.

OpenAI Batch API gives ~50% cost reduction versus the live Chat Completions
endpoint at the cost of a ≤24h async SLA. For our ~3200-image prod backfill
that's roughly $15 instead of $30 — and the async bound cleanly isolates
backfill cost from realtime traffic (separate rate limits, separate
accounting).

Workflow (four subcommands, each idempotent):

    prepare
        Query drive_files for image rows that need captioning, build an
        OpenAI Batch JSONL file locally, print row count + estimated cost.
        Does NOT call OpenAI. Safe to run anywhere.

    submit
        Re-runs prepare (or takes --input path), uploads the JSONL via
        the OpenAI Files API, creates a Batch job, prints the batch_id.
        Requires OPENAI_API_KEY. Respects --max-cost-usd preflight ceiling.

    status <batch_id>
        Prints the current status (validating, in_progress, completed,
        failed, cancelled, expired). No side effects.

    apply <batch_id>
        Downloads the results JSONL, runs person-safety post-validation
        per row, writes captions through enrich_scenes() (OpenSearch
        dual-write, scene_overrides gate), and stamps drive_files
        caption_status/caption_engine/caption_prompt_version/
        caption_generated_at.

Selection query:
    SELECT id, org_id, video_id, file_name FROM drive_files
    WHERE mime_type LIKE 'image/%'
      AND is_deleted = false
      AND (caption_status IS NULL
           OR caption_status != 'done'
           OR caption_prompt_version IS DISTINCT FROM :current_version)
    ORDER BY created_at ASC
    LIMIT :limit

Running the same prepare/submit/apply cycle twice is safe: already-done
rows for the current prompt version are excluded from the selection.

Usage:

    docker compose exec -T api python -m app.cli.backfill_image_caption_batch prepare --limit 3000 --output /tmp/img_caption_batch.jsonl
    docker compose exec -T api python -m app.cli.backfill_image_caption_batch submit --input /tmp/img_caption_batch.jsonl --max-cost-usd 30
    docker compose exec -T api python -m app.cli.backfill_image_caption_batch status <batch_id>
    docker compose exec -T api python -m app.cli.backfill_image_caption_batch apply <batch_id>
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Selection ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImageRow:
    drive_file_id: UUID
    org_id: UUID
    video_id: str
    file_name: str
    scene_id: str  # for images, scene_id is deterministic from video_id


async def select_image_rows(
    *,
    current_prompt_version: str,
    limit: int,
    org_slug: str | None = None,
) -> list[ImageRow]:
    """Find drive_files rows that need image captioning.

    Excludes rows already captioned at the current prompt version.
    Re-running prepare is safe — already-done rows drop out here.
    """

    # Force the full model registry to load before running any query.
    # Without this, SQLAlchemy fails to resolve relationships like
    # Org.users because only DriveFile's module has been imported.
    # Matches the pattern in app/cli/backfill.py:344.
    import app.db.models  # noqa: F401
    from sqlalchemy import or_, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.base import get_async_session_factory
    from app.modules.drive.models import DriveFile
    from app.modules.orgs.models import Org

    session_factory = get_async_session_factory()
    async with session_factory() as session:  # type: AsyncSession
        stmt = (
            select(
                DriveFile.id,
                DriveFile.org_id,
                DriveFile.video_id,
                DriveFile.file_name,
            )
            .where(
                DriveFile.mime_type.like("image/%"),
                DriveFile.is_deleted.is_(False),
                or_(
                    DriveFile.caption_status.is_(None),
                    DriveFile.caption_status != "done",
                    DriveFile.caption_prompt_version != current_prompt_version,
                    DriveFile.caption_prompt_version.is_(None),
                ),
            )
            .order_by(DriveFile.created_at.asc())
            .limit(limit)
        )

        if org_slug:
            org_row = (
                await session.execute(
                    select(Org.id).where(Org.slug == org_slug)
                )
            ).first()
            if org_row is None:
                raise ValueError(f"Unknown org slug: {org_slug!r}")
            stmt = stmt.where(DriveFile.org_id == org_row[0])

        rows = (await session.execute(stmt)).all()

    return [
        ImageRow(
            drive_file_id=r[0],
            org_id=r[1],
            video_id=r[2],
            file_name=r[3] or "",
            # Matches drive-worker/src/tasks/process.py:112 exactly —
            # image scenes use f"{video_id}_scene_000" (not "_s000").
            # Getting this wrong means every S3 keyframe fetch returns
            # a 404 and the whole backfill silently skips every row.
            scene_id=f"{r[2]}_scene_000",
        )
        for r in rows
    ]


# ─── JSONL build ──────────────────────────────────────────────────────────────


_MAX_IMAGE_DIM = 1024  # gpt-4o "detail": "low" internally downscales
                       # to 512x512, so anything above 1024 is wasted
                       # bytes in the Batch input file.
_JPEG_QUALITY = 85


def _maybe_shrink_image(image_bytes: bytes) -> tuple[bytes, str]:
    """Resize to at most _MAX_IMAGE_DIM on the longest side, re-encode
    as JPEG. Falls back to the original bytes (and 'image/jpeg' MIME) if
    PIL can't decode — lets tests pass fake byte fixtures unchanged.

    Returns (bytes, mime_type).
    """

    try:
        from PIL import Image  # lazy import: keeps test suite lightweight
        import io

        with Image.open(io.BytesIO(image_bytes)) as im:
            im.thumbnail((_MAX_IMAGE_DIM, _MAX_IMAGE_DIM))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=_JPEG_QUALITY)
            return buf.getvalue(), "image/jpeg"
    except Exception:
        return image_bytes, "image/jpeg"


def build_batch_request_line(
    *,
    row: ImageRow,
    image_bytes: bytes,
    model: str,
    image_detail: str,
    messages_prefix: list[dict[str, Any]],
    user_instruction: str,
    json_schema: dict[str, Any],
) -> dict[str, Any]:
    """Build one line of the Batch API input JSONL.

    custom_id uniquely identifies the scene and MUST round-trip in the
    response line so apply() can map results back.

    Image bytes are resized client-side (max 1024 px, JPEG quality 85)
    before base64 encoding so the 200-row staging batch fits comfortably
    under OpenAI's 100 MB input file limit, and prod's 3000-row batch
    stays workable without sharding.
    """

    shrunk_bytes, mime = _maybe_shrink_image(image_bytes)
    b64 = base64.b64encode(shrunk_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    hint = f"\n(참고: 파일명: {row.file_name})" if row.file_name else ""
    user_content: list[dict[str, Any]] = [
        {"type": "text", "text": user_instruction + hint},
        {
            "type": "image_url",
            "image_url": {"url": data_url, "detail": image_detail},
        },
    ]

    messages = list(messages_prefix) + [{"role": "user", "content": user_content}]

    return {
        "custom_id": f"{row.org_id}::{row.video_id}::{row.scene_id}",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": json_schema,
            },
            "temperature": 0,
            "seed": 42,
        },
    }


def _guess_mime(file_name: str) -> str:
    lower = file_name.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


# ─── Subcommand: prepare ──────────────────────────────────────────────────────


async def cmd_prepare(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.modules.drive.keys import enrichment_keyframe_s3_key
    from app.modules.image_caption.engines.openai_prompt import (
        JSON_SCHEMA,
        PROMPT_VERSION,
        SYSTEM_PROMPT,
        USER_INSTRUCTION,
    )
    from app.storage.s3 import S3Client

    settings = get_settings()
    prompt_version = settings.image_caption_prompt_version or PROMPT_VERSION
    model = settings.image_caption_model
    image_detail = settings.image_caption_image_detail
    est_cost_per_call = settings.image_caption_estimated_cost_per_call_usd
    # Batch API is 50% cheaper than the live API.
    est_cost_per_call_batch = est_cost_per_call * 0.5

    rows = await select_image_rows(
        current_prompt_version=prompt_version,
        limit=args.limit,
        org_slug=args.org,
    )
    if not rows:
        logger.info("prepare: no rows match the selection query")
        return 0

    est_cost = len(rows) * est_cost_per_call_batch

    logger.info(
        "prepare_plan",
        extra={
            "row_count": len(rows),
            "estimated_cost_usd_batch": round(est_cost, 4),
            "model": model,
            "prompt_version": prompt_version,
        },
    )
    print(f"Rows to caption: {len(rows)}")
    print(f"Model: {model}")
    print(f"Prompt version: {prompt_version}")
    print(f"Estimated cost (Batch API, ~50% off): ${est_cost:.4f}")

    if args.dry_run:
        print("--dry-run: no JSONL written")
        return 0

    if args.max_cost_usd is not None and est_cost > args.max_cost_usd:
        logger.error(
            "prepare_cost_exceeds_ceiling",
            extra={"estimated": est_cost, "ceiling": args.max_cost_usd},
        )
        print(
            f"ERROR: estimated ${est_cost:.4f} > ceiling ${args.max_cost_usd:.4f}"
        )
        return 2

    output_path = (
        Path(args.output)
        if args.output
        else Path(tempfile.gettempdir()) / f"img_caption_batch_{int(time.time())}.jsonl"
    )

    s3 = S3Client(bucket=settings.drive_s3_bucket)

    # IMPORTANT: Batch-mode messages use the system prompt ONLY — no
    # few-shot turns. Prompt caching does not apply to Batch requests
    # (each is independent), so including few-shots would pay the full
    # few-shot token cost on every row and quickly blow through the
    # org's enqueued-token limit (90k tokens for gpt-4o tier 1).
    #
    # Quality: few-shots demonstrated the output format; the strict
    # JSON schema enforces format structurally, and the system prompt
    # spells out tone/safety rules explicitly. The realtime path
    # (ImageCaptionService) keeps few-shots because caching makes them
    # effectively free there.
    messages_prefix: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]

    # Chunk size: keep each output file's total enqueued-token count
    # safely under the org's enqueued-token limit. With system-only
    # prefix (~600 tokens) + user turn w/ low-detail image (~150
    # tokens) = ~750 tokens per row, 100 rows = ~75k tokens (safe margin
    # under 90k).
    chunk_rows = args.chunk_rows
    chunk_index = 0
    chunk_written = 0
    total_written = 0
    failed = 0
    chunk_paths: list[Path] = []

    def _chunk_path(idx: int) -> Path:
        stem = output_path.stem
        suffix = output_path.suffix or ".jsonl"
        return output_path.with_name(f"{stem}.chunk{idx:03d}{suffix}")

    fh = _chunk_path(chunk_index).open("w", encoding="utf-8")
    chunk_paths.append(_chunk_path(chunk_index))
    try:
        for row in rows:
            s3_key = enrichment_keyframe_s3_key(
                str(row.org_id), row.video_id, row.scene_id
            )
            with tempfile.TemporaryDirectory() as td:
                local = Path(td) / "img.jpg"
                try:
                    await s3.download_file_async(s3_key, local)
                    image_bytes = local.read_bytes()
                except Exception as e:
                    logger.warning(
                        "prepare_skip_row",
                        extra={
                            "drive_file_id": str(row.drive_file_id),
                            "video_id": row.video_id,
                            "error": f"{type(e).__name__}: {e}",
                        },
                    )
                    failed += 1
                    continue

            line = build_batch_request_line(
                row=row,
                image_bytes=image_bytes,
                model=model,
                image_detail=image_detail,
                messages_prefix=messages_prefix,
                user_instruction=USER_INSTRUCTION,
                json_schema=JSON_SCHEMA,
            )
            fh.write(json.dumps(line, ensure_ascii=False))
            fh.write("\n")
            chunk_written += 1
            total_written += 1

            if chunk_written >= chunk_rows:
                fh.close()
                chunk_index += 1
                chunk_written = 0
                fh = _chunk_path(chunk_index).open("w", encoding="utf-8")
                chunk_paths.append(_chunk_path(chunk_index))
    finally:
        fh.close()

    # Drop trailing empty chunk, if any
    final_chunks = [p for p in chunk_paths if p.exists() and p.stat().st_size > 0]

    logger.info(
        "prepare_done",
        extra={
            "rows_written": total_written,
            "rows_skipped": failed,
            "chunk_count": len(final_chunks),
            "chunk_rows": chunk_rows,
        },
    )
    print(f"Wrote {total_written} rows (skipped {failed}) across {len(final_chunks)} chunk(s):")
    for p in final_chunks:
        size_kb = p.stat().st_size // 1024
        rows_in = sum(1 for _ in p.open("r", encoding="utf-8"))
        print(f"  {p}  ({rows_in} rows, {size_kb} KB)")
    return 0


# ─── Subcommand: submit ───────────────────────────────────────────────────────


def cmd_submit(args: argparse.Namespace) -> int:
    from app.config import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY is not set")
        return 2

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}")
        return 2

    row_count = sum(1 for _ in input_path.open("r", encoding="utf-8"))
    est_cost = row_count * settings.image_caption_estimated_cost_per_call_usd * 0.5

    if args.max_cost_usd is not None and est_cost > args.max_cost_usd:
        print(
            f"ERROR: estimated ${est_cost:.4f} > ceiling ${args.max_cost_usd:.4f}"
        )
        return 2

    print(f"Uploading {row_count} rows (~${est_cost:.4f}) ...")

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai SDK not installed")
        return 2

    client = OpenAI(api_key=settings.openai_api_key)

    uploaded = client.files.create(
        file=input_path.open("rb"),
        purpose="batch",
    )
    print(f"Uploaded file id: {uploaded.id}")

    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={
            "source": "heimdex_image_caption_backfill",
            "prompt_version": settings.image_caption_prompt_version,
            "row_count": str(row_count),
        },
    )
    print(f"Batch id: {batch.id}")
    print(f"Status:   {batch.status}")
    return 0


# ─── Subcommand: status ───────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from openai import OpenAI

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    batch = client.batches.retrieve(args.batch_id)
    print(f"Batch id: {batch.id}")
    print(f"Status:   {batch.status}")
    counts = getattr(batch, "request_counts", None)
    if counts is not None:
        print(f"Requests: total={counts.total} "
              f"completed={counts.completed} failed={counts.failed}")
    if batch.output_file_id:
        print(f"Output file id: {batch.output_file_id}")
    if batch.error_file_id:
        print(f"Error file id:  {batch.error_file_id}")
    return 0


# ─── Subcommand: apply ────────────────────────────────────────────────────────


async def cmd_apply(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    # Force full model registry load before any DB access — same fix as
    # in select_image_rows(). See backfill.py:344 for the pattern.
    import app.db.models  # noqa: F401
    from openai import OpenAI
    from sqlalchemy import update

    from app.config import get_settings
    from app.db.base import get_async_session_factory
    from app.modules.drive.models import DriveFile
    from app.modules.image_caption.engines.openai_prompt import (
        BANNED_PERSON_TERMS,
        PROMPT_VERSION,
    )
    from app.modules.image_caption.engines.post_validation import (
        assert_person_safety,
    )
    from app.modules.image_caption.engines.base import PersonSafetyViolation
    from app.modules.ingest.schemas import (
        EnrichScenesRequest,
        EnrichSceneUpdate,
    )
    from app.modules.ingest.service import SceneIngestService
    from app.modules.search.scene_client import SceneSearchClient

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    batch = client.batches.retrieve(args.batch_id)
    if batch.status != "completed":
        print(f"Batch not completed (status={batch.status}); aborting apply.")
        return 2

    if not batch.output_file_id:
        print("Batch has no output_file_id; aborting.")
        return 2

    content = client.files.content(batch.output_file_id).read()
    if isinstance(content, bytes):
        content = content.decode("utf-8")

    lines = [line for line in content.splitlines() if line.strip()]
    print(f"Batch output has {len(lines)} lines")

    prompt_version = (
        settings.image_caption_prompt_version or PROMPT_VERSION
    )
    model = settings.image_caption_model

    scene_client = SceneSearchClient()
    total_applied = 0
    total_safety_violations = 0
    total_parse_errors = 0

    try:
        session_factory = get_async_session_factory()
        for raw in lines:
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                total_parse_errors += 1
                continue

            custom_id = row.get("custom_id", "")
            try:
                org_str, video_id, scene_id = custom_id.split("::")
                org_id = UUID(org_str)
            except (ValueError, AttributeError):
                logger.warning(
                    "apply_bad_custom_id",
                    extra={"custom_id": custom_id},
                )
                total_parse_errors += 1
                continue

            response = row.get("response") or {}
            body = response.get("body") or {}
            choices = body.get("choices") or []
            if not choices:
                total_parse_errors += 1
                continue

            message = choices[0].get("message") or {}
            content_str = message.get("content") or ""
            try:
                parsed = json.loads(content_str)
            except json.JSONDecodeError:
                total_parse_errors += 1
                continue

            caption = (parsed.get("caption") or "").strip()
            has_person = bool(parsed.get("has_person", False))

            if not caption:
                total_parse_errors += 1
                continue

            try:
                assert_person_safety(caption, has_person, BANNED_PERSON_TERMS)
            except PersonSafetyViolation:
                total_safety_violations += 1
                logger.error(
                    "apply_person_safety_violation",
                    extra={
                        "custom_id": custom_id,
                        "caption_snippet": caption[:200],
                    },
                )
                async with session_factory() as session:
                    await session.execute(
                        update(DriveFile)
                        .where(
                            DriveFile.org_id == org_id,
                            DriveFile.video_id == video_id,
                        )
                        .values(
                            caption_status="failed",
                            caption_error="person_terms_leaked",
                        )
                    )
                    await session.commit()
                continue

            caption_text = caption[:5_000]

            async with session_factory() as session:
                ingest_service = SceneIngestService(
                    session=session,
                    scene_opensearch=scene_client,
                )
                await ingest_service.enrich_scenes(
                    request=EnrichScenesRequest(
                        video_id=video_id,
                        scenes=[
                            EnrichSceneUpdate(
                                scene_id=scene_id,
                                scene_caption=caption_text,
                            )
                        ],
                    ),
                    org_id=org_id,
                )
                await session.execute(
                    update(DriveFile)
                    .where(
                        DriveFile.org_id == org_id,
                        DriveFile.video_id == video_id,
                    )
                    .values(
                        caption_status="done",
                        caption_error=None,
                        caption_engine=model,
                        caption_prompt_version=prompt_version,
                        caption_generated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()

            total_applied += 1
    finally:
        await scene_client.close()

    print(f"Applied:            {total_applied}")
    print(f"Safety violations:  {total_safety_violations}")
    print(f"Parse errors:       {total_parse_errors}")
    return 0


# ─── Entrypoint ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_image_caption_batch",
        description="Image caption backfill via OpenAI Batch API",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="Build JSONL + cost estimate")
    p_prep.add_argument("--limit", type=int, default=3000)
    p_prep.add_argument("--org", default=None, help="Org slug filter")
    p_prep.add_argument(
        "--output",
        default=None,
        help="JSONL output path (chunks get .chunk000.jsonl, .chunk001.jsonl, ...)",
    )
    p_prep.add_argument("--dry-run", action="store_true")
    p_prep.add_argument("--max-cost-usd", type=float, default=None)
    p_prep.add_argument(
        "--chunk-rows",
        type=int,
        default=100,
        help=(
            "Max rows per Batch input file. Default 100 keeps each chunk "
            "under OpenAI's 90k-token enqueued limit for gpt-4o (system "
            "prompt + image ~750 tokens/row × 100 = ~75k)."
        ),
    )

    p_submit = sub.add_parser("submit", help="Upload JSONL + create batch")
    p_submit.add_argument("--input", required=True, help="JSONL path from prepare")
    p_submit.add_argument("--max-cost-usd", type=float, default=None)

    p_status = sub.add_parser("status", help="Check batch status")
    p_status.add_argument("batch_id")

    p_apply = sub.add_parser("apply", help="Pull results + write captions")
    p_apply.add_argument("batch_id")

    args = parser.parse_args()

    if args.cmd == "prepare":
        return asyncio.run(cmd_prepare(args))
    if args.cmd == "submit":
        return cmd_submit(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "apply":
        return asyncio.run(cmd_apply(args))
    return 1


if __name__ == "__main__":
    sys.exit(main())
