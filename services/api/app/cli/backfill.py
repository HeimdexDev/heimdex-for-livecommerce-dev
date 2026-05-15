"""Backfill enrichment jobs for indexed videos.

Republishes SQS enrichment messages for already-indexed videos so that
workers re-process them with updated models or feature flags.

Usage:
    python -m app.cli.backfill --target ai_tags --dry-run
    python -m app.cli.backfill --target ai_tags --org livenow --batch-size 20
    python -m app.cli.backfill --target caption --since 2026-03-01 --limit 100
    python -m app.cli.backfill --target visual_embed --org livenow --resume

Targets:
    ai_tags       Re-caption with VLM ai_tags (requires AI_TAGS_ENABLED=true)
    caption       Re-generate scene captions
    visual_embed  Re-generate SigLIP2 visual embeddings
    stt           Re-run speech-to-text
    ocr           Re-run OCR extraction
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Target registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BackfillTarget:
    name: str
    job_types: tuple[str, ...]
    status_field: str | None
    skip_statuses: frozenset[str]
    needs_keyframes: bool
    needs_audio: bool
    needs_transcript: bool

TARGETS: dict[str, BackfillTarget] = {
    "caption": BackfillTarget(
        name="caption",
        job_types=("caption",),
        status_field="caption_status",
        skip_statuses=frozenset({"done", "running"}),
        needs_keyframes=True,
        needs_audio=False,
        needs_transcript=True,
    ),
    "visual_embed": BackfillTarget(
        name="visual_embed",
        job_types=("visual_embed",),
        status_field=None,
        skip_statuses=frozenset(),
        needs_keyframes=True,
        needs_audio=False,
        needs_transcript=False,
    ),
    "stt": BackfillTarget(
        name="stt",
        job_types=("stt",),
        status_field="stt_status",
        skip_statuses=frozenset({"done", "running"}),
        needs_keyframes=False,
        needs_audio=True,
        needs_transcript=False,
    ),
    "ocr": BackfillTarget(
        name="ocr",
        job_types=("ocr",),
        status_field="ocr_status",
        skip_statuses=frozenset({"done", "running"}),
        needs_keyframes=True,
        needs_audio=False,
        needs_transcript=False,
    ),
    "ai_tags": BackfillTarget(
        name="ai_tags",
        job_types=("caption",),
        status_field="caption_status",
        skip_statuses=frozenset({"running"}),
        needs_keyframes=True,
        needs_audio=False,
        needs_transcript=True,
    ),
    "color": BackfillTarget(
        name="color",
        job_types=("color_extract",),
        status_field=None,
        skip_statuses=frozenset(),
        needs_keyframes=True,
        needs_audio=False,
        needs_transcript=False,
    ),
}


# ---------------------------------------------------------------------------
# Cursor state for resume
# ---------------------------------------------------------------------------

@dataclass
class CursorState:
    target: str
    last_created_at: str | None
    last_file_id: str | None
    total_files: int
    total_scenes: int
    started_at: str
    updated_at: str


def _load_cursor(state_file: str, target: str) -> CursorState | None:
    path = Path(state_file)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if data.get("target") != target:
            logger.warning(
                f"State file target mismatch: expected '{target}', "
                f"found '{data.get('target')}'. Starting fresh."
            )
            return None
        return CursorState(**data)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.warning(f"Could not parse state file: {e}. Starting fresh.")
        return None


def _save_cursor(state_file: str, state: CursorState) -> None:
    Path(state_file).write_text(json.dumps(state.__dict__, indent=2))


# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill enrichment jobs for indexed videos",
    )
    parser.add_argument(
        "--target", required=True, choices=list(TARGETS.keys()),
        help="Enrichment target to backfill",
    )
    parser.add_argument(
        "--org", type=str, default=None,
        help="Org slug or UUID. Omit for all orgs.",
    )
    parser.add_argument(
        "--video", type=str, default=None,
        help="Single video_id to reprocess (e.g. gd_bdbcd446a322267a)",
    )
    parser.add_argument(
        "--since", type=str, default=None,
        help="Only videos created after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until", type=str, default=None,
        help="Only videos created before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--library", type=str, default=None,
        help="Filter by library UUID",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max number of videos to process",
    )
    parser.add_argument(
        "--batch-size", type=int, default=50,
        help="Videos per DB query batch (default: 50)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds to sleep between batches (default: 1.0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Log what would be published without sending SQS messages",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from last saved cursor state",
    )
    parser.add_argument(
        "--state-file", type=str, default="/tmp/backfill_state.json",
        help="Path to cursor state file (default: /tmp/backfill_state.json)",
    )
    parser.add_argument(
        "--skip-idempotency", action="store_true",
        help="Force re-publish even if target enrichment appears done",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

async def _resolve_org_id(session: Any, org_arg: str) -> UUID:
    from app.modules.orgs.models import Org
    from sqlalchemy import select

    try:
        org_uuid = UUID(org_arg)
        result = await session.execute(select(Org).where(Org.id == org_uuid))
        org = result.scalar_one_or_none()
    except ValueError:
        result = await session.execute(select(Org).where(Org.slug == org_arg))
        org = result.scalar_one_or_none()

    if not org:
        logger.error(f"Org not found: {org_arg}")
        sys.exit(1)
    return org.id


async def _query_files(
    session: Any,
    target: BackfillTarget,
    org_id: UUID | None,
    library_id: UUID | None,
    since: date | None,
    until: date | None,
    skip_idempotency: bool,
    cursor_created_at: datetime | None,
    cursor_file_id: UUID | None,
    batch_size: int,
    video_id: str | None = None,
) -> list[Any]:
    from sqlalchemy import select, and_
    from app.modules.drive.models import DriveFile, DriveConnection

    q = (
        select(DriveFile)
        .where(DriveFile.processing_status == "indexed")
        .where(DriveFile.is_deleted.is_(False))
        .where(DriveFile.scene_count > 0)
    )

    if target.needs_keyframes:
        q = q.where(DriveFile.keyframe_s3_prefix.isnot(None))
    if target.needs_audio:
        q = q.where(DriveFile.audio_s3_key.isnot(None))

    if video_id:
        q = q.where(DriveFile.video_id == video_id)

    if org_id:
        q = q.where(DriveFile.org_id == org_id)

    if library_id:
        q = q.join(DriveConnection, DriveFile.connection_id == DriveConnection.id).where(
            DriveConnection.library_id == library_id
        )

    if since:
        q = q.where(DriveFile.created_at >= datetime(since.year, since.month, since.day, tzinfo=timezone.utc))
    if until:
        q = q.where(DriveFile.created_at < datetime(until.year, until.month, until.day, tzinfo=timezone.utc))

    if not skip_idempotency and target.status_field:
        status_col = getattr(DriveFile, target.status_field)
        q = q.where(
            (status_col.is_(None)) | (~status_col.in_(target.skip_statuses))
        )

    # Cursor-based pagination: skip already-processed files (newest first)
    if cursor_created_at and cursor_file_id:
        q = q.where(
            (DriveFile.created_at < cursor_created_at)
            | and_(DriveFile.created_at == cursor_created_at, DriveFile.id < cursor_file_id)
        )

    q = q.order_by(DriveFile.created_at.desc(), DriveFile.id.desc()).limit(batch_size)

    result = await session.execute(q)
    return list(result.scalars().all())


async def _process_file(
    file: Any,
    target: BackfillTarget,
    scene_client: Any | None,
    dry_run: bool,
) -> int:
    scenes: list[dict[str, Any]] = []
    for i in range(file.scene_count):
        scene_id = f"{file.video_id}_scene_{i:03d}"
        scene: dict[str, Any] = {
            "scene_id": scene_id,
            "scene_index": i,
            "keyframe_s3_key": f"{file.keyframe_s3_prefix}{scene_id}.jpg",
        }
        scenes.append(scene)

    # Fetch transcripts for caption/ai_tags targets
    if target.needs_transcript and scene_client:
        try:
            transcripts = await scene_client.get_scene_transcripts(
                str(file.org_id), file.video_id, file.scene_count
            )
            for scene in scenes:
                t = transcripts.get(scene["scene_id"], "")
                if t:
                    scene["transcript_raw"] = t
        except Exception:
            logger.debug(f"Could not fetch transcripts for {file.video_id}, proceeding without")

    if dry_run:
        return len(scenes)

    from app.sqs_producer import publish_scene_enrichment_jobs
    publish_scene_enrichment_jobs(
        file_id=file.id,
        org_id=file.org_id,
        video_id=file.video_id,
        scenes=scenes,
        job_types=target.job_types,
    )
    return len(scenes)


async def _run(args: argparse.Namespace) -> None:
    target = TARGETS[args.target]
    mode = "[DRY RUN] " if args.dry_run else ""

    logger.info(f"{mode}Backfill starting: target={args.target}")

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.db.base import get_async_engine
    import app.db.models  # noqa: F401

    engine = get_async_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Resolve org filter
    org_id: UUID | None = None
    if args.org:
        async with factory() as session:
            org_id = await _resolve_org_id(session, args.org)
        logger.info(f"Org filter: {args.org} -> {org_id}")

    library_id: UUID | None = UUID(args.library) if args.library else None
    since = date.fromisoformat(args.since) if args.since else None
    until = date.fromisoformat(args.until) if args.until else None

    # Optional OpenSearch client for transcript fetching
    scene_client = None
    if target.needs_transcript:
        from app.modules.search.scene_client import SceneSearchClient
        scene_client = SceneSearchClient()

    # Load or initialize cursor
    cursor: CursorState | None = None
    if args.resume:
        cursor = _load_cursor(args.state_file, args.target)
        if cursor:
            logger.info(
                f"Resuming from cursor: {cursor.total_files} files, "
                f"{cursor.total_scenes} scenes already processed"
            )

    total_files = cursor.total_files if cursor else 0
    total_scenes = cursor.total_scenes if cursor else 0
    skipped = 0
    started_at = cursor.started_at if cursor else datetime.now(timezone.utc).isoformat()

    cursor_created_at: datetime | None = None
    cursor_file_id: UUID | None = None
    if cursor and cursor.last_created_at and cursor.last_file_id:
        cursor_created_at = datetime.fromisoformat(cursor.last_created_at)
        cursor_file_id = UUID(cursor.last_file_id)

    try:
        batch_num = 0
        while True:
            async with factory() as session:
                files = await _query_files(
                    session, target, org_id, library_id,
                    since, until, args.skip_idempotency,
                    cursor_created_at, cursor_file_id, args.batch_size,
                    video_id=args.video,
                )

            if not files:
                logger.info("No more files to process.")
                break

            batch_num += 1
            batch_files = 0
            batch_scenes = 0

            for file in files:
                scenes_published = await _process_file(file, target, scene_client, args.dry_run)
                if scenes_published > 0:
                    total_files += 1
                    batch_files += 1
                    total_scenes += scenes_published
                    batch_scenes += scenes_published
                else:
                    skipped += 1

                cursor_created_at = file.created_at
                cursor_file_id = file.id

            # Save cursor after each batch
            if not args.dry_run:
                state = CursorState(
                    target=args.target,
                    last_created_at=cursor_created_at.isoformat() if cursor_created_at else None,
                    last_file_id=str(cursor_file_id) if cursor_file_id else None,
                    total_files=total_files,
                    total_scenes=total_scenes,
                    started_at=started_at,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )
                _save_cursor(args.state_file, state)

            logger.info(
                f"{mode}Batch {batch_num}: {batch_files} files, {batch_scenes} scenes | "
                f"Total: {total_files} files, {total_scenes} scenes, {skipped} skipped"
            )

            # Check limit
            if args.limit and total_files >= args.limit:
                logger.info(f"Reached limit of {args.limit} files.")
                break

            # Rate limit between batches
            if args.delay > 0 and not args.dry_run:
                time.sleep(args.delay)

    finally:
        if scene_client:
            await scene_client.close()

    logger.info(
        f"{mode}Backfill complete: target={args.target} "
        f"files={total_files} scenes={total_scenes} skipped={skipped}"
    )


def main() -> None:
    import asyncio
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
