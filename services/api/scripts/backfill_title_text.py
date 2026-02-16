from __future__ import annotations

import argparse
import asyncio
import sys
import unicodedata
from typing import Any, cast

from app.modules.search.scene_client import SceneSearchClient


def _build_args() -> bool:
    parser = argparse.ArgumentParser(prog="backfill_title_text")
    _ = parser.add_argument("--dry-run", action="store_true", help="Only count docs that would be updated")
    parsed = parser.parse_args()
    return cast(bool, parsed.dry_run)


async def _scroll_all_docs(
    scene_client: SceneSearchClient,
) -> list[dict[str, Any]]:
    """Fetch all docs with video_title via scroll API."""
    docs: list[dict[str, Any]] = []
    body: dict[str, Any] = {
        "size": 500,
        "query": {"match_all": {}},
        "_source": ["video_title"],
        "sort": ["_doc"],
    }
    response = await scene_client.client.search(
        index=scene_client.alias_name,
        body=body,
        params={"scroll": "2m"},
    )
    scroll_id = response.get("_scroll_id")
    hits = response["hits"]["hits"]
    docs.extend(hits)

    while hits:
        response = await scene_client.client.scroll(
            scroll_id=scroll_id,
            params={"scroll": "2m"},
        )
        hits = response["hits"]["hits"]
        docs.extend(hits)

    if scroll_id:
        try:
            await scene_client.client.clear_scroll(scroll_id=scroll_id)
        except Exception:
            pass

    return docs


async def _run() -> int:
    dry_run = _build_args()
    scene_client = SceneSearchClient()
    try:
        all_docs = await _scroll_all_docs(scene_client)
        print(f"Total documents: {len(all_docs)}")

        # Build bulk update actions with NFC-normalized video_title_text.
        # Korean text from macOS filenames or some APIs arrives in NFD
        # (decomposed Jamo), which the Nori tokenizer cannot match against
        # NFC search queries.  Normalizing to NFC fixes this.
        actions: list[dict[str, Any]] = []
        nfc_count = 0
        for doc in all_docs:
            doc_id = doc["_id"]
            source = doc.get("_source", {})
            video_title = source.get("video_title", "") or ""
            title_nfc = unicodedata.normalize("NFC", video_title)
            if title_nfc != video_title:
                nfc_count += 1
            actions.append({"update": {"_index": scene_client.index_name, "_id": doc_id}})
            actions.append({"doc": {"video_title_text": title_nfc}})

        print(f"Documents needing NFC normalization: {nfc_count}")
        print(f"Documents to update: {len(all_docs)}")

        if dry_run:
            return 0

        batch_size = 500
        total_updated = 0
        for i in range(0, len(actions), batch_size * 2):
            batch = actions[i : i + batch_size * 2]
            response = await scene_client.client.bulk(
                body=batch,
                params={"refresh": "false"},
            )
            if response.get("errors"):
                error_items = [
                    item for item in response.get("items", [])
                    if "error" in item.get("update", {})
                ]
                print(f"Batch errors: {len(error_items)}", file=sys.stderr)
                for err in error_items[:3]:
                    print(f"  {err}", file=sys.stderr)
            total_updated += len(batch) // 2

        await scene_client.client.indices.refresh(index=scene_client.index_name)
        print(f"Backfill complete. updated={total_updated} nfc_normalized={nfc_count}")
        return 0
    except Exception as exc:
        print(f"Backfill failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await scene_client.close()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
