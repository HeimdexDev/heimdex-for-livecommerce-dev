"""
Re-embed all scenes with caption-first embeddings (AD-2 migration).

Creates a v2 index, scrolls through all scenes in the source index,
rebuilds embedding text using build_embedding_text() (caption + transcript
+ ocr), generates new E5 embeddings, and bulk-indexes into the target
index with embedding_version="v2_caption".

The script does NOT swap the alias — that is done separately by bumping
INDEX_VERSION in scene_client.py and running promote_alias_to_current_version().

Usage:
    # Dry run — count docs, show sample embedding texts, no writes
    python -m scripts.reembed_scenes --dry-run

    # Full migration into v2
    python -m scripts.reembed_scenes --batch-size 32

    # Custom source/target (e.g. non-default prefix)
    python -m scripts.reembed_scenes --source heimdex_scenes_v1 --target heimdex_scenes_v2

    # Filter by org
    python -m scripts.reembed_scenes --org-id 4d20264c-c440-4d69-8613-7d7558ea386b
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

from app.modules.ingest.service import build_embedding_text
from app.modules.search.embedding import get_passage_embeddings_batch
from app.modules.search.scene_client import SceneSearchClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMBEDDING_VERSION = "v2_caption"
SCROLL_SIZE = 500
SCROLL_TIMEOUT = "5m"
SOURCE_FIELDS = [
    "org_id",
    "scene_id",
    "transcript_norm",
    "ocr_text_norm",
    "scene_caption",
]

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reembed_scenes",
        description="Re-embed scenes with caption-first embeddings (AD-2).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count docs and show sample texts without writing.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Number of scenes to embed per batch (default: 32).",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source index name (default: auto-detect from SceneSearchClient).",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Target index name (default: {prefix}_scenes_v2).",
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
        "_source": True,  # need full doc for re-index
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
    """Create the target index with the same mapping as the current version.

    Does NOT attach the alias — alias swap is a separate step.
    """
    exists = await client.client.indices.exists(index=target_index)
    if exists:
        print(f"Target index '{target_index}' already exists, reusing it.")
        return

    # Reuse the same create_index logic but for a specific target name.
    # We read the mapping from the client's create_index method output.
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
            "people_cluster_ids": {"type": "keyword"},
            "keyword_tags": {"type": "keyword"},
            "product_tags": {"type": "keyword"},
            "product_entities": {"type": "keyword"},
            "speech_segment_count": {"type": "integer"},
            "keyframe_timestamp_ms": {"type": "integer"},
            "thumbnail_url": {"type": "keyword", "index": False},
            "source_type": {"type": "keyword"},
            "web_view_link": {"type": "keyword", "index": False},
            "required_drive_nickname": {"type": "keyword"},
            "source_path": {"type": "keyword"},
            "capture_time": {"type": "date"},
            "ingest_time": {"type": "date"},
            "embedding_version": {"type": "keyword"},
        }
    }

    # Create WITHOUT alias — alias swap is done separately after validation
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

    source_index = args.source or scene_client.index_name  # heimdex_scenes_v1
    target_index = args.target or f"{scene_client.alias_name}_v2"

    print(f"Source: {source_index}")
    print(f"Target: {target_index}")
    print(f"Batch size: {args.batch_size}")
    print(f"Embedding version: {EMBEDDING_VERSION}")
    if args.org_id:
        print(f"Org filter: {args.org_id}")
    print()

    try:
        # 1. Scroll all docs from source
        t_start = time.monotonic()
        all_docs = await _scroll_all_scenes(scene_client, source_index, args.org_id)
        t_scroll = time.monotonic()
        print(f"Scrolled {len(all_docs)} scenes ({t_scroll - t_start:.1f}s)")

        if not all_docs:
            print("No scenes found. Nothing to do.")
            return 0

        # 2. Build embedding texts and show samples
        embed_texts: list[tuple[int, str]] = []
        skipped_no_text = 0
        for i, doc in enumerate(all_docs):
            src = doc["_source"]
            transcript = src.get("transcript_norm", "") or ""
            ocr = src.get("ocr_text_norm", "") or ""
            caption = src.get("scene_caption", "") or ""

            text = build_embedding_text(transcript, ocr, caption)
            if text:
                embed_texts.append((i, text))
            else:
                skipped_no_text += 1

        print(f"Scenes with text: {len(embed_texts)}")
        print(f"Scenes without text (no embedding): {skipped_no_text}")

        # Show 3 sample embedding texts
        if embed_texts:
            print("\nSample embedding texts:")
            for idx, (doc_idx, text) in enumerate(embed_texts[:3]):
                scene_id = all_docs[doc_idx]["_source"].get("scene_id", "?")
                preview = text[:120] + "..." if len(text) > 120 else text
                print(f"  [{idx + 1}] {scene_id}: {preview}")
            print()

        if args.dry_run:
            print("Dry run complete. No writes performed.")
            return 0

        # 3. Create target index (if not exists)
        await _ensure_target_index(scene_client, target_index)

        # 4. Batch embed and write to target
        t_embed_start = time.monotonic()
        total_embedded = 0
        embeddings: dict[int, list[float]] = {}

        for batch_start in range(0, len(embed_texts), args.batch_size):
            batch = embed_texts[batch_start:batch_start + args.batch_size]
            texts = [t for _, t in batch]
            vectors = get_passage_embeddings_batch(texts)
            for (doc_idx, _), vec in zip(batch, vectors):
                embeddings[doc_idx] = vec
            total_embedded += len(batch)

            if total_embedded % 100 == 0 or total_embedded == len(embed_texts):
                elapsed = time.monotonic() - t_embed_start
                rate = total_embedded / elapsed if elapsed > 0 else 0
                print(
                    f"  Embedded {total_embedded}/{len(embed_texts)} "
                    f"({elapsed:.1f}s, {rate:.0f} scenes/s)"
                )

        t_embed_end = time.monotonic()
        print(f"Embedding complete: {total_embedded} scenes ({t_embed_end - t_embed_start:.1f}s)")

        # 5. Bulk index all docs into target with new embeddings
        t_index_start = time.monotonic()
        bulk_actions: list[dict[str, Any]] = []
        for i, doc in enumerate(all_docs):
            doc_id = doc["_id"]
            new_doc = dict(doc["_source"])

            # Replace embedding if we have a new one
            if i in embeddings:
                new_doc["embedding_vector"] = embeddings[i]
            # else: keep original embedding_vector (if any) from source

            new_doc["embedding_version"] = EMBEDDING_VERSION

            bulk_actions.append({"index": {"_index": target_index, "_id": doc_id}})
            bulk_actions.append(new_doc)

        # Write in batches
        write_batch_size = 200
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

        # 6. Verify
        count_response = await scene_client.client.count(index=target_index)
        target_count = count_response["count"]
        source_count_response = await scene_client.client.count(index=source_index)
        source_count = source_count_response["count"]

        t_total = time.monotonic() - t_start

        print()
        print("=" * 60)
        print("Migration Summary")
        print("=" * 60)
        print(f"  Source scenes:     {source_count}")
        print(f"  Target scenes:     {target_count}")
        print(f"  Embedded:          {total_embedded}")
        print(f"  Skipped (no text): {skipped_no_text}")
        print(f"  Write errors:      {errors_total}")
        print(f"  Scroll time:       {t_scroll - t_start:.1f}s")
        print(f"  Embed time:        {t_embed_end - t_embed_start:.1f}s")
        print(f"  Index time:        {t_index_end - t_index_start:.1f}s")
        print(f"  Total time:        {t_total:.1f}s")
        print()

        if target_count != source_count:
            count_msg = "COUNT MISMATCH"
            if args.org_id:
                count_msg += f" (expected — org filter active, source has {source_count} total)"
            print(f"  ⚠ {count_msg}", file=sys.stderr)

        if target_count == source_count and errors_total == 0:
            print("✓ Migration complete. Ready for alias swap.")
            print()
            print("Next steps:")
            print("  1. Verify: curl $OS_URL/" + target_index + "/_count")
            print("  2. Bump INDEX_VERSION = 'v2' in scene_client.py")
            print("  3. Deploy to staging")
            print("  4. ensure_index_exists() will auto-promote alias")
        else:
            print("⚠ Review warnings above before proceeding.")

        return 0 if errors_total == 0 else 1

    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        await scene_client.close()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
