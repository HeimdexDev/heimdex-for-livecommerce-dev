"""Direct color backfill: S3 keyframes → color extraction → OpenSearch update.

Runs inside the API container. No SQS, no worker needed.
Scrolls all scenes missing color_embedding, downloads keyframes from S3,
extracts dominant colors, and bulk-updates OpenSearch.

Usage:
    python -m app.cli.backfill_colors_direct
    python -m app.cli.backfill_colors_direct --limit 100
    python -m app.cli.backfill_colors_direct --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import io
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Direct color backfill from S3 keyframes")
    parser.add_argument("--limit", type=int, default=0, help="Max scenes to process (0=unlimited)")
    parser.add_argument("--batch-size", type=int, default=100, help="Scenes per scroll batch")
    parser.add_argument("--dry-run", action="store_true", help="Count only, no updates")
    return parser.parse_args()


async def _backfill(limit: int, batch_size: int, dry_run: bool) -> None:
    import boto3
    from PIL import Image

    from app.config import get_settings
    from app.modules.search.color_extraction import (
        colors_to_hex,
        extract_dominant_colors,
        rgb_to_hsl_histogram,
    )
    from app.modules.search.scene_client import SceneSearchClient

    settings = get_settings()
    s3 = boto3.client("s3", region_name=settings.s3_region)
    bucket = settings.drive_s3_bucket
    client = SceneSearchClient()

    body = {
        "query": {"bool": {"must_not": [{"exists": {"field": "color_embedding"}}]}},
        "size": batch_size,
        "_source": ["scene_id", "video_id", "org_id"],
        "sort": [{"_doc": "asc"}],
    }

    total = 0
    success = 0
    errors = 0

    while True:
        if limit > 0 and total >= limit:
            break

        response = await client.client.search(index=client.alias_name, body=body)
        hits = response["hits"]["hits"]
        if not hits:
            break

        updates: list[tuple[str, dict]] = []
        for hit in hits:
            if limit > 0 and total >= limit:
                break

            src = hit["_source"]
            doc_id = hit["_id"]
            org_id = src["org_id"]
            video_id = src["video_id"]
            scene_id = src["scene_id"]
            s3_key = f"{org_id}/drive/keyframes/{video_id}/{scene_id}.jpg"

            if dry_run:
                total += 1
                success += 1
                continue

            try:
                obj = s3.get_object(Bucket=bucket, Key=s3_key)
                raw = obj["Body"].read()
                obj["Body"].close()
                buf = io.BytesIO(raw)
                img = Image.open(buf).convert("RGB")
                colors, weights = extract_dominant_colors(img, k=5)
                histogram = rgb_to_hsl_histogram(colors, weights)
                hex_colors = colors_to_hex(colors[:5])
                img.close()
                buf.close()
                del raw
                updates.append((doc_id, {"color_embedding": histogram, "dominant_colors": hex_colors}))
                success += 1
            except s3.exceptions.NoSuchKey:
                errors += 1
            except Exception:
                errors += 1

            total += 1

        if updates:
            # Write via alias (not versioned index_name) to target active index
            actions: list[dict] = []
            for doc_id, partial in updates:
                actions.append({"update": {"_index": client.alias_name, "_id": doc_id}})
                actions.append({"doc": partial})
            await client.client.bulk(body=actions, params={"refresh": "true"})

        logger.info("progress: total=%d success=%d errors=%d", total, success, errors)
        gc.collect()

        body["search_after"] = hits[-1]["sort"]

    # Final count
    verify_body = {"query": {"exists": {"field": "color_embedding"}}, "size": 0}
    verify_resp = await client.client.search(index=client.alias_name, body=verify_body)
    color_count = verify_resp["hits"]["total"]["value"]

    logger.info("done: total=%d success=%d errors=%d color_docs=%d", total, success, errors, color_count)
    await client.close()


def main() -> None:
    args = _parse_args()
    asyncio.run(_backfill(limit=args.limit, batch_size=args.batch_size, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
