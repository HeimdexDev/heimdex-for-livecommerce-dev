"""Requeue face detection for drive_files where it never ran or failed.

Usage:
    python -m app.cli.requeue_face_detection                       # full sweep
    python -m app.cli.requeue_face_detection --dry-run              # report only
    python -m app.cli.requeue_face_detection --limit 50             # cap batch
    python -m app.cli.requeue_face_detection --include-failed       # also retry face_status='failed'
    python -m app.cli.requeue_face_detection --org-id <uuid>        # single-org

Why:
    Face detection runs on Aircloud (see ``project_aircloud_worker_pattern.md``).
    Some drive_files end up with ``face_status IS NULL`` because they were
    indexed before the face worker was provisioned, because the SQS publish
    silently failed, or because the keyframe extraction step finished after
    the face publish hook ran. This CLI sweeps such rows and republishes a
    single face job per file. The auto-shorts feature (P0 prerequisite)
    needs the corpus fully covered for human-mode and product-mode hard
    filters to work correctly.

Behavior:
    * Selects ``DriveFile`` rows where ``face_status IS NULL`` AND
      ``keyframe_s3_prefix IS NOT NULL`` (no point publishing a face job
      with no keyframes — the worker would no-op).
    * With ``--include-failed``, also picks up ``face_status='failed'``.
    * Publishes a face job via the existing ``_publish('face', ...)`` path
      so the wake-orchestrator semantics, message attributes, and
      deduplication ID format match every other face job.
    * Updates ``face_status`` to ``'queued'`` on success (so re-running the
      CLI doesn't double-publish).
    * Per-row failures are logged and skipped — never abort the sweep.

Known limitation:
    ``sqs_producer._publish`` is fire-and-forget and swallows SQS client
    errors internally. If an SQS send silently drops a message after
    reporting success at the boto3 layer, the row will still get flipped
    to ``face_status='queued'`` and future runs of this CLI won't pick it
    up. Mitigations: (a) run ``--dry-run`` first, (b) monitor the face
    queue depth and DLQ after the sweep, (c) re-run with
    ``--include-failed`` after any worker DLQ drain if you suspect a
    silent loss. Move to a synchronous SQS send that re-raises if this
    becomes a recurring operational issue.

Exit codes:
    0  success (zero or more rows processed, including partial failures)
    1  fatal pre-sweep error (config invalid, DB unreachable)

Run via the EC2 deploy wrapper:
    ssh ec2-user@<host> "cd /opt/heimdex/dev-heimdex-for-livecommerce && \\
        docker compose exec -T api python -m app.cli.requeue_face_detection --dry-run"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Republish face-detection SQS jobs for unprocessed drive_files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print rows that would be requeued; do not publish or update DB.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of rows to requeue this run. Default: no limit.",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Also requeue rows with face_status='failed' (default: only NULL).",
    )
    parser.add_argument(
        "--org-id",
        type=str,
        default=None,
        help="Restrict sweep to a single org_id (UUID).",
    )
    return parser.parse_args()


async def _run(
    *,
    dry_run: bool,
    limit: int | None,
    include_failed: bool,
    org_id: str | None,
) -> int:
    # Lazy imports — keep `--help` cheap and DB-free.
    from sqlalchemy import or_, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import get_settings
    from app.db.base import get_async_engine
    import app.db.models  # noqa: F401 — load model registry
    from app.modules.drive.models import DriveFile
    # ``_publish`` is the same function the API uses on every ingest path
    # (it wraps _wake_gpu_worker + structured logging + dedup ID). Calling
    # it directly from the CLI keeps the message shape + side effects
    # identical to the happy path. The underscore is a module-visibility
    # hint, not a "don't call it" — we'd have to duplicate ~50 lines to
    # avoid the import. Revisit if sqs_producer ever gets a public
    # ``publish_face_job`` helper.
    from app.sqs_producer import _publish  # noqa: PLC2701 — intentional

    settings = get_settings()
    if not settings.sqs_face_queue_url and not dry_run:
        logger.error(
            "sqs_face_queue_url not set; refusing to publish "
            "(use --dry-run to inspect candidates without SQS)."
        )
        return 1

    engine = get_async_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    requeued = 0
    failures = 0
    skipped_no_keyframes = 0

    # Postgres ``IN (NULL)`` does not match NULL rows — NULL is not equal
    # to anything, including itself. Build the predicate with
    # ``IS NULL`` explicitly, OR'd with the failed case when
    # ``--include-failed`` is set.
    status_predicates = [DriveFile.face_status.is_(None)]
    if include_failed:
        status_predicates.append(DriveFile.face_status == "failed")

    async with factory() as session:
        stmt = (
            select(DriveFile)
            .where(or_(*status_predicates))
            .order_by(DriveFile.created_at.asc())
        )
        if org_id:
            try:
                org_uuid = UUID(org_id)
            except ValueError:
                logger.error("--org-id must be a valid UUID, got: %r", org_id)
                return 1
            stmt = stmt.where(DriveFile.org_id == org_uuid)
        if limit is not None:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        logger.info("requeue_face_candidates_found", extra={"count": len(rows), "dry_run": dry_run})

        for row in rows:
            if not row.keyframe_s3_prefix:
                # Face worker reads keyframes from this prefix; no point
                # publishing without it. drive-worker should fix this on its
                # own once transcode catches up.
                skipped_no_keyframes += 1
                logger.info(
                    "requeue_face_skipped_no_keyframes",
                    extra={
                        "file_id": str(row.id),
                        "video_id": row.video_id,
                        "org_id": str(row.org_id),
                    },
                )
                continue

            if dry_run:
                logger.info(
                    "requeue_face_would_publish",
                    extra={
                        "file_id": str(row.id),
                        "org_id": str(row.org_id),
                        "video_id": row.video_id,
                        "current_status": row.face_status,
                    },
                )
                continue

            try:
                now = datetime.now(timezone.utc)
                _publish(
                    "face",
                    {
                        "version": "1",
                        "type": "enrichment.job_created",
                        "timestamp": now.isoformat(),
                        "job_type": "face",
                        "file_id": str(row.id),
                        "org_id": str(row.org_id),
                        "video_id": row.video_id,
                        "keyframe_s3_prefix": row.keyframe_s3_prefix,
                        "audio_s3_key": None,
                    },
                    f"{row.id}:face:requeue:{now.strftime('%Y%m%dT%H%M')}",
                )
                row.face_status = "queued"
                requeued += 1
            except Exception:
                failures += 1
                logger.exception(
                    "requeue_face_publish_failed",
                    extra={"file_id": str(row.id), "video_id": row.video_id},
                )
                continue

        if not dry_run:
            await session.commit()

    logger.info(
        "requeue_face_done dry_run=%s candidates=%d requeued=%d "
        "skipped_no_keyframes=%d failures=%d",
        dry_run,
        len(rows),
        requeued,
        skipped_no_keyframes,
        failures,
    )
    return 0


def main() -> None:
    args = _parse_args()
    try:
        exit_code = asyncio.run(
            _run(
                dry_run=args.dry_run,
                limit=args.limit,
                include_failed=args.include_failed,
                org_id=args.org_id,
            )
        )
    except Exception:
        logger.exception("requeue_face_detection crashed")
        sys.exit(1)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
