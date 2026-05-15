"""
Reprocess drive files through the full pipeline (resplit + enrichment cascade).

Publishes resplit SQS jobs for each indexed video. The drive-worker
re-splits scenes in place using the supplied scene_params; on completion
the internal PATCH /internal/videos/{video_id}/reprocess/{job_id}/status
handler auto-publishes both v1 (STT, OCR, face) and v2 (caption,
visual_embed) enrichment jobs.

Net effect: one resplit publish per video kicks off the entire pipeline.
Pre-existing STT data is loaded from S3 and reused by the resplitter to
keep speech-aware segmentation intact across runs.

Usage (run inside the API container on staging EC2):

    # Dry run — show videos that would be reprocessed
    docker compose exec -T api python -m scripts.reprocess_pipeline --dry-run --org-slug devorg

    # Full devorg reprocess with the new 15s max-scene cap
    docker compose exec -T api python -m scripts.reprocess_pipeline --org-slug devorg --max-scene-duration-ms 15000

    # Smoke-test against 3 videos first
    docker compose exec -T api python -m scripts.reprocess_pipeline --org-slug devorg --limit 3
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from sqlalchemy import create_engine, text

from app.config import get_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reprocess_pipeline",
        description="Reprocess drive files via resplit (full enrichment cascade).",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="List videos that would be reprocessed without publishing.")
    org_group = parser.add_mutually_exclusive_group()
    org_group.add_argument("--org-id", type=str, default=None,
                           help="Filter by org UUID.")
    org_group.add_argument("--org-slug", type=str, default=None,
                           help="Filter by org slug (resolved to UUID).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of videos to reprocess.")
    parser.add_argument("--max-scene-duration-ms", type=int, default=15_000,
                        help="Max scene duration in ms (default: 15000).")
    parser.add_argument("--min-scene-duration-ms", type=int, default=500,
                        help="Min scene duration in ms (default: 500).")
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="Visual scene-cut threshold (default: 0.3).")
    parser.add_argument("--split-preset", type=str, default=None,
                        help="Optional named preset (default/fine/coarse/visual_only).")
    parser.add_argument("--use-speech", action="store_true", default=True,
                        help="Honor existing STT data for speech-aware splitting (default: on).")
    parser.add_argument("--no-use-speech", dest="use_speech", action="store_false",
                        help="Disable speech-aware splitting (visual cuts only).")
    return parser.parse_args()


def _resolve_org_id(engine: Any, org_id: str | None, org_slug: str | None) -> str | None:
    if org_id:
        return org_id
    if not org_slug:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM orgs WHERE slug = :slug"),
            {"slug": org_slug},
        ).fetchone()
    if row is None:
        print(f"ERROR: org slug '{org_slug}' not found.", file=sys.stderr)
        sys.exit(1)
    return str(row[0])


def _fetch_videos(
    engine: Any,
    org_id: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    """Indexed drive_files joined with drive_connections for library_id."""
    query = """
        SELECT
            d.id AS file_id,
            d.org_id,
            d.video_id,
            d.proxy_s3_key,
            d.keyframe_s3_prefix,
            d.audio_s3_key,
            d.file_name,
            c.library_id
        FROM drive_files d
        JOIN drive_connections c ON c.id = d.connection_id
        WHERE d.processing_status = 'indexed'
          AND d.is_deleted = false
          AND d.proxy_s3_key IS NOT NULL
          AND c.library_id IS NOT NULL
    """
    params: dict[str, Any] = {}
    if org_id:
        query += " AND d.org_id = :org_id"
        params["org_id"] = org_id
    query += " ORDER BY d.created_at ASC"
    if limit:
        query += " LIMIT :limit"
        params["limit"] = limit

    with engine.connect() as conn:
        rows = conn.execute(text(query), params).fetchall()

    return [
        {
            "file_id": str(r[0]),
            "org_id": str(r[1]),
            "video_id": r[2],
            "proxy_s3_key": r[3],
            "keyframe_s3_prefix": r[4] or "",
            "audio_s3_key": r[5] or "",
            "file_name": r[6] or r[2],
            "library_id": str(r[7]),
        }
        for r in rows
    ]


def _create_reprocess_jobs(
    engine: Any,
    videos: list[dict[str, Any]],
    scene_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Insert one row per video into scene_reprocess_jobs. Returns enriched dicts with job_id."""
    now = datetime.now(timezone.utc)
    enriched: list[dict[str, Any]] = []
    with engine.begin() as conn:
        for v in videos:
            job_id = str(uuid.uuid4())
            conn.execute(
                text("""
                    INSERT INTO scene_reprocess_jobs (
                        id, org_id, video_id, source_type,
                        scene_params, proxy_s3_key,
                        status, created_at, updated_at
                    ) VALUES (
                        :id, :org_id, :video_id, :source_type,
                        CAST(:scene_params AS JSONB), :proxy_s3_key,
                        'pending', :created_at, :updated_at
                    )
                """),
                {
                    "id": job_id,
                    "org_id": v["org_id"],
                    "video_id": v["video_id"],
                    "source_type": "gdrive",
                    "scene_params": json.dumps(scene_params),
                    "proxy_s3_key": v["proxy_s3_key"],
                    "created_at": now,
                    "updated_at": now,
                },
            )
            enriched.append({**v, "job_id": job_id})
    return enriched


def _publish_resplit_messages(
    videos: list[dict[str, Any]],
    queue_url: str,
    region: str,
    endpoint_url: str | None,
    scene_params: dict[str, Any],
) -> tuple[int, int]:
    kwargs: dict[str, Any] = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    client = boto3.client("sqs", **kwargs)

    published = 0
    failed = 0
    for v in videos:
        now = datetime.now(timezone.utc)
        body = {
            "version": "1",
            "type": "resplit.job_created",
            "timestamp": now.isoformat(),
            "job_id": v["job_id"],
            "org_id": v["org_id"],
            "video_id": v["video_id"],
            "source_type": "gdrive",
            "proxy_s3_key": v["proxy_s3_key"],
            "keyframe_s3_prefix": v["keyframe_s3_prefix"],
            "audio_s3_key": v["audio_s3_key"],
            "library_id": v["library_id"],
            "video_title": v["file_name"],
            "scene_params": scene_params,
        }
        try:
            resp = client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(body, default=str),
                MessageAttributes={
                    "job_type": {"StringValue": "resplit", "DataType": "String"},
                    "org_id": {"StringValue": v["org_id"], "DataType": "String"},
                    "source": {"StringValue": "reprocess_pipeline_script", "DataType": "String"},
                },
            )
            published += 1
            print(f"  [{published}/{len(videos)}] {v['video_id']} "
                  f"({v['file_name'][:50]}) → {resp.get('MessageId', '?')[:12]}")
        except Exception as exc:
            failed += 1
            print(f"  [FAIL] {v['video_id']} ({v['file_name'][:50]}): "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
    return published, failed


def main() -> int:
    args = _parse_args()
    settings = get_settings()

    queue_url = settings.sqs_processing_queue_url
    if not queue_url:
        print("ERROR: SQS_PROCESSING_QUEUE_URL is not configured.", file=sys.stderr)
        return 1
    db_url = settings.database_url_sync
    if not db_url:
        print("ERROR: DATABASE_URL_SYNC is not configured.", file=sys.stderr)
        return 1

    scene_params: dict[str, Any] = {
        "min_scene_duration_ms": args.min_scene_duration_ms,
        "max_scene_duration_ms": args.max_scene_duration_ms,
        "threshold": args.threshold,
        "split_preset": args.split_preset,
        "use_speech": args.use_speech,
    }

    print("=" * 64)
    print("Full-Pipeline Reprocess (resplit → enrichment cascade)")
    print("=" * 64)
    print(f"  Queue:          {queue_url}")
    print(f"  Org filter:     {args.org_slug or args.org_id or 'all'}")
    print(f"  Limit:          {args.limit or 'none'}")
    print(f"  Scene params:   {json.dumps(scene_params)}")
    print(f"  Dry run:        {args.dry_run}")
    print()

    engine = create_engine(db_url)
    org_id = _resolve_org_id(engine, args.org_id, args.org_slug)

    t0 = time.monotonic()
    videos = _fetch_videos(engine, org_id, args.limit)
    print(f"Found {len(videos)} reprocessable videos ({time.monotonic() - t0:.1f}s)")

    if not videos:
        print("Nothing to reprocess.")
        return 0

    if args.dry_run:
        print()
        print("Videos that would be reprocessed:")
        for i, v in enumerate(videos, 1):
            print(f"  [{i:>3}] {v['video_id']} — {v['file_name'][:60]}")
        print()
        print(f"Dry run complete. {len(videos)} videos would be reprocessed.")
        return 0

    print()
    print("Inserting scene_reprocess_jobs rows…")
    enriched = _create_reprocess_jobs(engine, videos, scene_params)
    print(f"Inserted {len(enriched)} pending job rows.")
    print()
    print("Publishing resplit SQS messages:")
    published, failed = _publish_resplit_messages(
        enriched,
        queue_url=queue_url,
        region=settings.sqs_region,
        endpoint_url=settings.sqs_endpoint_url or None,
        scene_params=scene_params,
    )

    print()
    print("=" * 64)
    print("Summary")
    print("=" * 64)
    print(f"  Total videos:  {len(enriched)}")
    print(f"  Published:     {published}")
    print(f"  Failed:        {failed}")
    print(f"  Elapsed:       {time.monotonic() - t0:.1f}s")
    print()
    print("Each resplit completion will auto-publish enrichment (STT, OCR, face,")
    print("caption, visual_embed). Monitor scene_reprocess_jobs.status for progress:")
    print("  SELECT status, COUNT(*) FROM scene_reprocess_jobs")
    print("    WHERE created_at > NOW() - INTERVAL '2 hours' GROUP BY status;")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
