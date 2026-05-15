"""
Reprocess all drive files through the STT pipeline via SQS.

Queries Postgres drive_files for all files with audio_s3_key in a given org,
then publishes one SQS message per file to the STT queue. The STT worker
on Aircloud+ picks up each message, re-transcribes with speaker diarization,
and posts enriched data back via /internal/ingest/enrich.

Usage (run inside the API container on staging EC2):

    # Dry run — show files that would be reprocessed
    python -m scripts.reprocess_stt --dry-run

    # Reprocess all files in the staging org
    python -m scripts.reprocess_stt

    # Reprocess a specific org
    python -m scripts.reprocess_stt --org-id 4d20264c-c440-4d69-8613-7d7558ea386b

    # Limit to N files (for testing)
    python -m scripts.reprocess_stt --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
import boto3
from sqlalchemy import create_engine, text

from app.config import get_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reprocess_stt",
        description="Reprocess drive files through STT pipeline via SQS.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be reprocessed without publishing.",
    )
    parser.add_argument(
        "--org-id",
        type=str,
        default=None,
        help="Filter by org_id (default: all orgs).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of files to reprocess (default: all).",
    )
    return parser.parse_args()


def _fetch_files(
    db_url: str,
    org_id: str | None,
    limit: int | None,
) -> list[dict]:
    """Query drive_files for files with audio_s3_key."""
    engine = create_engine(db_url)

    query = """
        SELECT id, org_id, video_id, audio_s3_key, file_name
        FROM drive_files
        WHERE audio_s3_key IS NOT NULL
          AND is_deleted = false
    """
    params: dict = {}

    if org_id:
        query += " AND org_id = :org_id"
        params["org_id"] = org_id

    query += " ORDER BY created_at ASC"

    if limit:
        query += " LIMIT :limit"
        params["limit"] = limit

    with engine.connect() as conn:
        result = conn.execute(text(query), params)
        rows = result.fetchall()

    return [
        {
            "file_id": str(row[0]),
            "org_id": str(row[1]),
            "video_id": row[2],
            "audio_s3_key": row[3],
            "file_name": row[4],
        }
        for row in rows
    ]


def _publish_stt_messages(
    files: list[dict],
    queue_url: str,
    region: str,
    endpoint_url: str | None,
) -> tuple[int, int]:
    """Publish STT v1 SQS messages for each file. Returns (published, failed)."""
    kwargs: dict = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    client = boto3.client("sqs", **kwargs)

    published = 0
    failed = 0

    for file in files:
        now = datetime.now(timezone.utc)
        body = {
            "version": "1",
            "type": "enrichment.job_created",
            "timestamp": now.isoformat(),
            "job_type": "stt",
            "file_id": file["file_id"],
            "org_id": file["org_id"],
            "video_id": file["video_id"],
            "keyframe_s3_prefix": None,
            "audio_s3_key": file["audio_s3_key"],
        }

        try:
            resp = client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(body, default=str),
                MessageAttributes={
                    "job_type": {"StringValue": "stt", "DataType": "String"},
                    "org_id": {
                        "StringValue": file["org_id"],
                        "DataType": "String",
                    },
                    "source": {"StringValue": "reprocess_script", "DataType": "String"},
                },
            )
            published += 1
            print(
                f"  [{published}] {file['video_id']} "
                f"({file['file_name'][:50]}) → {resp.get('MessageId', '?')[:12]}"
            )
        except Exception as exc:
            failed += 1
            print(
                f"  [FAIL] {file['video_id']} ({file['file_name'][:50]}): "
                + f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    return published, failed


def main() -> int:
    args = _parse_args()
    settings = get_settings()

    # Validate SQS config
    queue_url = settings.sqs_stt_queue_url
    if not queue_url:
        print("ERROR: SQS_STT_QUEUE_URL is not configured.", file=sys.stderr)
        return 1

    db_url = settings.database_url_sync
    if not db_url:
        print("ERROR: DATABASE_URL_SYNC is not configured.", file=sys.stderr)
        return 1

    print("=" * 60)
    print("STT Reprocessing (Speaker Diarization Backfill)")
    print("=" * 60)
    print(f"  Queue:    {queue_url}")
    print(f"  Org:      {args.org_id or 'all'}")
    print(f"  Limit:    {args.limit or 'none'}")
    print(f"  Dry run:  {args.dry_run}")
    print()

    # Fetch files from Postgres
    t_start = time.monotonic()
    files = _fetch_files(db_url, args.org_id, args.limit)
    t_fetch = time.monotonic()

    print(f"Found {len(files)} files with audio ({t_fetch - t_start:.1f}s)")
    print()

    if not files:
        print("No files to reprocess.")
        return 0

    if args.dry_run:
        print("Files that would be reprocessed:")
        for i, f in enumerate(files, 1):
            print(f"  [{i}] {f['video_id']} — {f['file_name'][:60]}")
        print()
        print(f"Dry run complete. {len(files)} files would be reprocessed.")
        return 0

    # Publish SQS messages
    print("Publishing STT jobs to SQS:")
    published, failed = _publish_stt_messages(
        files,
        queue_url=queue_url,
        region=settings.sqs_region,
        endpoint_url=settings.sqs_endpoint_url or None,
    )

    t_total = time.monotonic() - t_start
    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Total files:  {len(files)}")
    print(f"  Published:    {published}")
    print(f"  Failed:       {failed}")
    print(f"  Time:         {t_total:.1f}s")
    print()

    if failed:
        print(f"WARNING: {failed} messages failed to publish.", file=sys.stderr)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
