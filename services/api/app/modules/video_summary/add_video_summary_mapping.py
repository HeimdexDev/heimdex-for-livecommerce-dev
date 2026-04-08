"""One-off script to add video_summary field to the live scene index.

Uses put_mapping (additive) — no reindex, no downtime, no version bump.

Usage:
    python -m app.modules.video_summary.add_video_summary_mapping
    python -m app.modules.video_summary.add_video_summary_mapping --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VIDEO_SUMMARY_MAPPING = {
    "properties": {
        "video_summary": {
            "type": "text",
            "analyzer": "standard",
            "fields": {
                "nori": {
                    "type": "text",
                    "analyzer": "nori_analyzer",
                }
            },
        },
    }
}

# Fallback mapping when Nori analyzer is not available (local dev)
VIDEO_SUMMARY_MAPPING_FALLBACK = {
    "properties": {
        "video_summary": {
            "type": "text",
            "analyzer": "standard",
        },
    }
}


async def _apply_mapping(dry_run: bool = False) -> None:
    from app.modules.search.scene_client import SceneSearchClient

    client = SceneSearchClient()
    index_name = client.alias_name

    logger.info(f"Target index: {index_name}")
    logger.info("Mapping to add: video_summary (text, Nori analyzed)")

    if dry_run:
        logger.info("[DRY RUN] Would apply put_mapping — no changes made.")
        await client.close()
        return

    try:
        await client.client.indices.put_mapping(
            index=index_name,
            body=VIDEO_SUMMARY_MAPPING,
        )
        logger.info(f"Successfully added video_summary field to {index_name} (with Nori)")
    except Exception:
        logger.info("Nori analyzer not available, falling back to standard analyzer")
        await client.client.indices.put_mapping(
            index=index_name,
            body=VIDEO_SUMMARY_MAPPING_FALLBACK,
        )
        logger.info(f"Successfully added video_summary field to {index_name} (standard)")

    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add video_summary mapping to scene index")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without applying")
    args = parser.parse_args()
    asyncio.run(_apply_mapping(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
