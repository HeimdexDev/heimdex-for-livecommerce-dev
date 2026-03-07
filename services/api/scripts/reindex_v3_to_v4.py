"""
Reindex scenes from v3 to v4, adding content_type: "video" to all documents.

Creates a v4 index, scrolls through all scenes in the v3 index,
adds content_type: "video" to each document, and bulk-indexes into the v4 index.

The script does NOT swap the alias — that is done separately by running
promote_alias_to_current_version().

Usage:
    # Dry run — count docs, no writes
    python -m scripts.reindex_v3_to_v4 --dry-run

    # Full migration into v4
    python -m scripts.reindex_v3_to_v4

    # Custom source/target
    python -m scripts.reindex_v3_to_v4 --source heimdex_scenes_v3 --target heimdex_scenes_v4

    # Filter by org
    python -m scripts.reindex_v3_to_v4 --org-id 4d20264c-c440-4d69-8613-7d7558ea386b
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

from app.modules.search.scene_client import SceneSearchClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCROLL_SIZE = 500
SCROLL_TIMEOUT = "5m"

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reindex_v3_to_v4",
        description="Reindex scenes from v3 to v4, adding content_type field.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count docs without writing.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source index name (default: heimdex_scenes_v3).",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Target index name (default: heimdex_scenes_v4).",
    )
    parser.add_argument(
        "--org-id",
        type=str,
        default=None,
        help="Filter by org_id (default: all orgs).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Scroll helper
# ---------------------------------------------------------------------------


async def _scroll_all_scenes(
    client: SceneSearchClient,
    source_index: str,
    org_id: str | None = None,
) -> list[dict[str, Any]]:
    """Scroll through all scenes in the source index."""
    query: dict[str, Any] = {"match_all": {}}
    if org_id:
        query = {"term": {"org_id": org_id}}

    body: dict[str, Any] = {
        "size": SCROLL_SIZE,
        "query": query,
        "_source": True,
        "sort": ["_doc"],
    }

    response = await client.client.search(
        index=source_index,
        body=body,
        params={"scroll": SCROLL_TIMEOUT},
    )
    scroll_id = response.get("_scroll_id")
    hits = response["hits"]["hits"]
    docs: list[dict[str, Any]] = list(hits)

    while hits:
        response = await client.client.scroll(
            scroll_id=scroll_id,
            params={"scroll": SCROLL_TIMEOUT},
        )
        hits = response["hits"]["hits"]
        docs.extend(hits)

    if scroll_id:
        try:
            await client.client.clear_scroll(scroll_id=scroll_id)
        except Exception:
            pass

    return docs


# ---------------------------------------------------------------------------
# Index creation
# ---------------------------------------------------------------------------


async def _ensure_target_index(
    client: SceneSearchClient,
    target_index: str,
) -> None:
    """Create the target index with v4 mapping."""
    exists = await client.client.indices.exists(index=target_index)
    if exists:
        print(f"Target index '{target_index}' already exists, reusing it.")
        return

    nori_available = await client._check_nori_available()
    transcript_analyzer = "korean_analyzer" if nori_available else "fallback_analyzer"

    settings: dict[str, Any] = {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "knn": True,
            "knn.algo_param.ef_search": 100,
        },
        "analysis": {
            "tokenizer": {
                "korean_tokenizer": {
                    "type": "nori_tokenizer",
                    "decompound_mode": "mixed",
                    "discard_punctuation": False,
                },
            } if nori_available else {},
            "filter": {
                "korean_pos_filter": {
                    "type": "nori_part_of_speech",
                    "stoptags": [
                        "E", "IC", "J", "MAG", "MAJ", "MM",
                        "SP", "SSC", "SSO", "SC", "SE",
                        "XPN", "XSA", "XSN", "XSV",
                        "UNA", "NA", "VSV",
                    ],
                },
            } if nori_available else {},
            "analyzer": {
                **({"korean_analyzer": {
                    "type": "custom",
                    "tokenizer": "korean_tokenizer",
                    "filter": ["lowercase", "korean_pos_filter", "nori_readingform"],
                }} if nori_available else {}),
                "fallback_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
            },
        },
    }

    mappings: dict[str, Any] = {
        "properties": {
            "org_id": {"type": "keyword"},
            "library_id": {"type": "keyword"},
            "video_id": {"type": "keyword"},
            "video_title": {
                "type": "keyword",
                "fields": {
                    "nori": {
                        "type": "text",
                        "analyzer": transcript_analyzer,
                        "search_analyzer": transcript_analyzer,
                    }
                },
            },
            "scene_id": {"type": "keyword"},
            "start_ms": {"type": "integer"},
            "end_ms": {"type": "integer"},
            "transcript_raw": {"type": "text"},
            "transcript_norm": {
                "type": "text",
                "analyzer": transcript_analyzer,
                "search_analyzer": transcript_analyzer,
            },
            "transcript_char_count": {"type": "integer"},
            "ocr_text_raw": {"type": "text"},
            "ocr_text_norm": {
                "type": "text",
                "analyzer": transcript_analyzer,
                "search_analyzer": transcript_analyzer,
            },
            "ocr_char_count": {"type": "integer"},
            "scene_caption": {
                "type": "text",
                "analyzer": transcript_analyzer,
                "search_analyzer": transcript_analyzer,
            },
            "embedding_vector": {
                "type": "knn_vector",
                "dimension": SceneSearchClient.EMBEDDING_DIMENSION,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                    "parameters": {"ef_construction": 128, "m": 24},
                },
            },
            "visual_embedding": {
                "type": "knn_vector",
                "dimension": 768,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                    "parameters": {"ef_construction": 128, "m": 24},
                },
            },
            "people_cluster_ids": {"type": "keyword"},
            "keyword_tags": {"type": "keyword"},
            "product_tags": {"type": "keyword"},
            "product_entities": {"type": "keyword"},
            "speech_segment_count": {"type": "integer"},
            "speaker_count": {"type": "integer"},
            "speaker_transcript": {"type": "text"},
            "keyframe_timestamp_ms": {"type": "integer"},
            "thumbnail_url": {"type": "keyword", "index": False},
            "source_type": {"type": "keyword"},
            "web_view_link": {"type": "keyword", "index": False},
            "required_drive_nickname": {"type": "keyword"},
            "source_path": {"type": "keyword"},
            "capture_time": {"type": "date"},
            "ingest_time": {"type": "date"},
            "embedding_version": {"type": "keyword"},
            "content_type": {"type": "keyword"},
            "image_width": {"type": "integer"},
            "image_height": {"type": "integer"},
            "image_orientation": {"type": "keyword"},
            "filename_text": {
                "type": "text",
                "analyzer": transcript_analyzer,
                "search_analyzer": transcript_analyzer,
            },
            "video_fps": {"type": "float"},
            "video_width": {"type": "integer"},
            "video_height": {"type": "integer"},
        }
    }

    await client.client.indices.create(
        index=target_index,
        body={"settings": settings, "mappings": mappings},
    )
    print(f"Created target index '{target_index}'.")


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------


async def _run() -> int:
    args = _parse_args()
    scene_client = SceneSearchClient()

    source_index = args.source or "heimdex_scenes_v3"
    target_index = args.target or "heimdex_scenes_v4"

    print(f"Source: {source_index}")
    print(f"Target: {target_index}")
    if args.org_id:
        print(f"Org filter: {args.org_id}")
    print()

    try:
        t_start = time.monotonic()
        all_docs = await _scroll_all_scenes(scene_client, source_index, args.org_id)
        t_scroll = time.monotonic()
        print(f"Scrolled {len(all_docs)} scenes ({t_scroll - t_start:.1f}s)")

        if not all_docs:
            print("No scenes found. Nothing to do.")
            return 0

        if args.dry_run:
            print("Dry run complete. No writes performed.")
            return 0

        await _ensure_target_index(scene_client, target_index)

        t_index_start = time.monotonic()
        bulk_actions: list[dict[str, Any]] = []
        for doc in all_docs:
            doc_id = doc["_id"]
            new_doc = dict(doc["_source"])
            new_doc["content_type"] = "video"

            bulk_actions.append({"index": {"_index": target_index, "_id": doc_id}})
            bulk_actions.append(new_doc)

        write_batch_size = 500
        total_written = 0
        errors_total = 0
        for i in range(0, len(bulk_actions), write_batch_size * 2):
            batch = bulk_actions[i:i + write_batch_size * 2]
            response = await scene_client.client.bulk(
                body=batch,
                params={"refresh": "false"},
            )
            batch_count = len(batch) // 2
            total_written += batch_count

            if response.get("errors"):
                error_items = [
                    item for item in response.get("items", [])
                    if "error" in item.get("index", {})
                ]
                errors_total += len(error_items)
                print(f"  Batch errors: {len(error_items)}", file=sys.stderr)
                for err in error_items[:3]:
                    print(f"    {err}", file=sys.stderr)

        await scene_client.client.indices.refresh(index=target_index)
        t_index_end = time.monotonic()

        count_response = await scene_client.client.count(index=target_index)
        target_count = count_response["count"]
        source_count_response = await scene_client.client.count(index=source_index)
        source_count = source_count_response["count"]

        t_total = time.monotonic() - t_start

        print()
        print("=" * 60)
        print("Reindex Summary")
        print("=" * 60)
        print(f"  Source scenes:  {source_count}")
        print(f"  Target scenes:  {target_count}")
        print(f"  Write errors:   {errors_total}")
        print(f"  Scroll time:    {t_scroll - t_start:.1f}s")
        print(f"  Index time:     {t_index_end - t_index_start:.1f}s")
        print(f"  Total time:     {t_total:.1f}s")
        print()

        if target_count != source_count:
            count_msg = "COUNT MISMATCH"
            if args.org_id:
                count_msg += f" (expected — org filter active, source has {source_count} total)"
            print(f"  ⚠ {count_msg}", file=sys.stderr)

        if target_count == source_count and errors_total == 0:
            print("✓ Reindex complete. Ready for alias swap.")
            print()
            print("Next steps:")
            print("  1. Verify: curl $OS_URL/" + target_index + "/_count")
            print("  2. Run 'python -m app.modules.search.promote_alias' to swap alias")
        else:
            print("⚠ Review warnings above before proceeding.")

        return 0 if errors_total == 0 else 1

    except Exception as exc:
        print(f"Reindex failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        await scene_client.close()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
