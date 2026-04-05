"""One-off script to add color_embedding and dominant_colors fields to the live scene index.

Uses put_mapping (additive) — no reindex, no downtime, no version bump.

Usage:
    python -m app.modules.search.add_color_mapping
    python -m app.modules.search.add_color_mapping --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

COLOR_EMBEDDING_DIMENSION = 27

COLOR_MAPPING = {
    "properties": {
        "color_embedding": {
            "type": "knn_vector",
            "dimension": COLOR_EMBEDDING_DIMENSION,
            "method": {
                "name": "hnsw",
                "space_type": "cosinesimil",
                "engine": "lucene",
                "parameters": {"ef_construction": 128, "m": 16},
            },
        },
        "dominant_colors": {"type": "keyword", "index": False},
    }
}


async def _apply_mapping(dry_run: bool = False) -> None:
    from app.modules.search.scene_client import SceneSearchClient

    client = SceneSearchClient()
    # Use alias to target whichever physical index is active
    index_name = client.alias_name

    logger.info(f"Target index: {index_name}")
    logger.info(f"Mapping to add: color_embedding ({COLOR_EMBEDDING_DIMENSION}-dim kNN), dominant_colors (keyword)")

    if dry_run:
        logger.info("[DRY RUN] Would apply put_mapping — no changes made.")
        await client.close()
        return

    await client.client.indices.put_mapping(
        index=index_name,
        body=COLOR_MAPPING,
    )
    logger.info(f"Successfully added color fields to {index_name}")
    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Add color mapping to scene index")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without applying")
    args = parser.parse_args()
    asyncio.run(_apply_mapping(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
