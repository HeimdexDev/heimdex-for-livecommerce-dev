"""
One-off repair for videos whose resplit predated the scene_manifest upload fix.

Context
-------
Pre-fix, resplit re-wrote scenes in OpenSearch + Postgres but never
refreshed ``scene_manifest_s3_key(org, video).scenes.json`` on S3. The
STT worker reads that manifest to map whisper segments to scenes. As
a result, after the 2026-04-24 devorg full-pipeline reprocess, every
scene on the affected videos had transcript_raw='' and
speech_segment_count=0.

What this script does
---------------------
For each target video:
  1. Query OpenSearch for all scenes (ordered by start_ms).
  2. Rebuild the scenes.json manifest in the shape the STT worker
     expects (video_id, video_title, library_id, total_duration_ms,
     scenes[] with scene_id/index/start_ms/end_ms/keyframe_timestamp_ms).
  3. Upload to scene_manifest_s3_key(org_id, video_id) — overwrites
     the stale manifest in place.
  4. Publish an STT enrichment SQS job so the STT worker re-runs
     whisper and emits per-scene transcripts against the NEW
     manifest boundaries.

Safe to re-run — each step is idempotent.

Usage (run inside the API container on staging):
    docker compose exec -T api python -m scripts.repair_scene_manifest_and_requeue_stt --dry-run --org-slug devorg
    docker compose exec -T api python -m scripts.repair_scene_manifest_and_requeue_stt --org-slug devorg
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import boto3

from app.config import get_settings


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="repair_scene_manifest_and_requeue_stt")
    p.add_argument("--dry-run", action="store_true")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--org-id", type=str, default=None)
    g.add_argument("--org-slug", type=str, default=None)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--video-id", type=str, default=None,
                   help="Repair a single video by ID (smoke test).")
    return p.parse_args()


async def _resolve_org_id(engine, org_id: str | None, org_slug: str | None) -> str | None:
    from sqlalchemy import text
    if org_id:
        return org_id
    if not org_slug:
        return None
    with engine.connect() as c:
        row = c.execute(text("SELECT id FROM orgs WHERE slug=:s"), {"s": org_slug}).fetchone()
    if not row:
        print(f"ERROR: org slug {org_slug!r} not found", file=sys.stderr)
        sys.exit(1)
    return str(row[0])


async def _list_videos(org_id: str | None, limit: int | None, video_id: str | None, engine) -> list[dict[str, Any]]:
    from sqlalchemy import text
    q = """
        SELECT d.id, d.org_id, d.video_id, d.file_name, d.audio_s3_key,
               d.keyframe_s3_prefix, d.proxy_duration_ms, c.library_id
        FROM drive_files d
        JOIN drive_connections c ON c.id = d.connection_id
        WHERE d.processing_status = 'indexed'
          AND d.is_deleted = false
          AND d.proxy_s3_key IS NOT NULL
          AND d.audio_s3_key IS NOT NULL
    """
    params: dict[str, Any] = {}
    if org_id:
        q += " AND d.org_id = :org_id"
        params["org_id"] = org_id
    if video_id:
        q += " AND d.video_id = :video_id"
        params["video_id"] = video_id
    q += " ORDER BY d.created_at ASC"
    if limit:
        q += " LIMIT :limit"
        params["limit"] = limit
    with engine.connect() as c:
        rows = c.execute(text(q), params).fetchall()
    return [
        {
            "file_id": str(r[0]),
            "org_id": str(r[1]),
            "video_id": r[2],
            "file_name": r[3] or r[2],
            "audio_s3_key": r[4],
            "keyframe_s3_prefix": r[5] or "",
            "duration_ms": int(r[6] or 0),
            "library_id": str(r[7]),
        }
        for r in rows
    ]


async def _fetch_scenes_from_os(org_id: str, video_id: str) -> list[dict[str, Any]]:
    from app.modules.search.scene_client import SceneSearchClient
    c = SceneSearchClient()
    try:
        resp = await c.client.search(
            index=c.alias_name,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"org_id": org_id}},
                            {"term": {"video_id": video_id}},
                        ]
                    }
                },
                "_source": ["scene_id", "start_ms", "end_ms", "keyframe_timestamp_ms"],
                "size": 5000,
                "sort": [{"start_ms": "asc"}],
            },
        )
    finally:
        await c.close()
    hits = resp.get("hits", {}).get("hits", [])
    out: list[dict[str, Any]] = []
    for h in hits:
        src = h.get("_source") or {}
        sid = src.get("scene_id") or ""
        # Derive index from scene_id suffix (OS doesn't store index).
        index = -1
        marker = "_scene_"
        if marker in sid:
            try:
                index = int(sid[sid.rfind(marker) + len(marker):])
            except ValueError:
                pass
        if index < 0:
            continue
        out.append(
            {
                "scene_id": sid,
                "index": index,
                "start_ms": int(src.get("start_ms", 0)),
                "end_ms": int(src.get("end_ms", 0)),
                "keyframe_timestamp_ms": int(src.get("keyframe_timestamp_ms", 0)),
            }
        )
    out.sort(key=lambda s: s["index"])
    return out


def _upload_manifest(s3_client, bucket: str, key: str, manifest: dict[str, Any]) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest).encode("utf-8"),
        ContentType="application/json",
    )


def _publish_stt_job(
    sqs_client, queue_url: str, video: dict[str, Any]
) -> str:
    now = datetime.now(timezone.utc)
    body = {
        "version": "1",
        "type": "enrichment.job_created",
        "timestamp": now.isoformat(),
        "job_type": "stt",
        "file_id": video["file_id"],
        "org_id": video["org_id"],
        "video_id": video["video_id"],
        "keyframe_s3_prefix": video["keyframe_s3_prefix"],
        "audio_s3_key": video["audio_s3_key"],
    }
    resp = sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(body, default=str),
        MessageAttributes={
            "job_type": {"StringValue": "stt", "DataType": "String"},
            "org_id": {"StringValue": video["org_id"], "DataType": "String"},
            "source": {"StringValue": "repair_script", "DataType": "String"},
        },
    )
    return resp.get("MessageId", "?")


async def _run(args: argparse.Namespace) -> int:
    from sqlalchemy import create_engine

    from heimdex_worker_sdk.drive_keys import scene_manifest_s3_key

    settings = get_settings()
    bucket = settings.drive_s3_bucket
    stt_queue_url = settings.sqs_stt_queue_url
    if not bucket or not stt_queue_url:
        print("ERROR: DRIVE_S3_BUCKET or SQS_STT_QUEUE_URL not configured", file=sys.stderr)
        return 1

    engine = create_engine(settings.database_url_sync)
    org_id = await _resolve_org_id(engine, args.org_id, args.org_slug)
    videos = await _list_videos(org_id, args.limit, args.video_id, engine)

    print("=" * 64)
    print("Scene-manifest repair + STT requeue")
    print("=" * 64)
    print(f"  Org:         {args.org_slug or args.org_id or 'all'}")
    print(f"  Video filter:{args.video_id or 'none'}")
    print(f"  Limit:       {args.limit or 'none'}")
    print(f"  Dry run:     {args.dry_run}")
    print(f"  Found:       {len(videos)} videos")
    print()

    if not videos:
        print("Nothing to repair.")
        return 0

    s3_client = boto3.client("s3", region_name=settings.s3_region)
    sqs_client = boto3.client("sqs", region_name=settings.sqs_region)

    t0 = time.monotonic()
    repaired = 0
    skipped = 0
    failed = 0
    for i, v in enumerate(videos, 1):
        scenes = await _fetch_scenes_from_os(v["org_id"], v["video_id"])
        if not scenes:
            print(f"  [{i}/{len(videos)}] {v['video_id']} — SKIP (no OS scenes)")
            skipped += 1
            continue

        manifest = {
            "video_id": v["video_id"],
            "video_title": v["file_name"],
            "library_id": v["library_id"],
            "total_duration_ms": v["duration_ms"],
            "scenes": scenes,
        }
        key = scene_manifest_s3_key(v["org_id"], v["video_id"])

        if args.dry_run:
            print(f"  [{i}/{len(videos)}] {v['video_id']} — would upload {len(scenes)} scenes → {key}")
            repaired += 1
            continue

        try:
            _upload_manifest(s3_client, bucket, key, manifest)
            msg_id = _publish_stt_job(sqs_client, stt_queue_url, v)
            print(f"  [{i}/{len(videos)}] {v['video_id']} — manifest:{len(scenes)} scenes  stt_msg:{msg_id[:12]}")
            repaired += 1
        except Exception as exc:
            failed += 1
            print(f"  [FAIL] {v['video_id']}: {type(exc).__name__}: {exc}", file=sys.stderr)

    print()
    print("=" * 64)
    print(f"Repaired:    {repaired}")
    print(f"Skipped:     {skipped}")
    print(f"Failed:      {failed}")
    print(f"Elapsed:     {time.monotonic() - t0:.1f}s")
    print()
    print("Each STT requeue triggers whisper re-run + per-scene enrichment")
    print("via /internal/ingest/enrich. Monitor:")
    print("  SELECT video_id, stt_status FROM drive_files WHERE updated_at > NOW()-INTERVAL '1 hour';")

    return 0 if failed == 0 else 1


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
