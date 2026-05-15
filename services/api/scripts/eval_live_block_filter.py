"""Observability harness for the Phase 0 live-block segmenter.

Runs ``partition_live_blocks`` over real OS scene data for one or
more videos and prints the predicted Phase 1 impact:

* Total / live / excluded scene counts
* Total / live / excluded duration in seconds
* Per-block (start_s, end_s, scene_count, duration_s)
* Exclusion percentage

Does NOT change behavior anywhere — no writes, no flags flipped, no
clip-source pool modified. Phase 1 will plug the same filter into
the picker once these numbers are spot-checked.

Manual only — NOT in CI. Pairs with ``.claude/plans/`` (this is the
Phase 0 deliverable from the auto-shorts product segmentation
iteration on 2026-05-14).

Runs INSIDE the api container (needs Postgres + OS access via the
existing app.modules.* code paths).

Usage::

    # On staging:
    ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63
    cd /opt/heimdex/dev-heimdex-for-livecommerce
    docker compose exec -T api python -m scripts.eval_live_block_filter \\
        --org devorg gd_75f4fab4913c2bb1

    # Multiple videos at once:
    docker compose exec -T api python -m scripts.eval_live_block_filter \\
        --org devorg gd_75f4fab4913c2bb1 gd_<other> gd_<other2>

    # JSON output for downstream processing:
    docker compose exec -T api python -m scripts.eval_live_block_filter \\
        --org devorg --json gd_75f4fab4913c2bb1

Exit codes:
    0 — ran successfully (no assertions; this is a measurement tool)
    2 — runner error (org not found, OS unreachable, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import text

from app.db.base import get_async_session_factory
from app.modules.search.scene_client import SceneSearchClient
from app.modules.shorts_auto_product.track_stt.segmentation import (
    partition_live_blocks,
    summarize,
)


async def _resolve_org_id(slug: str) -> str | None:
    SF = get_async_session_factory()
    async with SF() as s:
        row = (
            await s.execute(text("SELECT id FROM orgs WHERE slug = :s"), {"s": slug})
        ).first()
    return str(row.id) if row else None


async def _fetch_all_scenes(
    client: SceneSearchClient, org_id: str, video_id: str
) -> list[dict[str, Any]]:
    """Page through all scenes for a video — OS default page is 50."""
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = await client.get_video_scenes(
            org_id=org_id, video_id=video_id, page_size=200, offset=offset
        )
        batch = resp.get("scenes", []) if isinstance(resp, dict) else []
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 200:
            break
        offset += len(batch)
    return out


def _render_text(video_id: str, scenes: list[dict[str, Any]]) -> str:
    blocks = partition_live_blocks(scenes)
    summary = summarize(scenes, blocks)

    lines: list[str] = []
    lines.append(f"=== {video_id} ===")
    lines.append(
        f"scenes:    total={summary.total_scenes:>4}  "
        f"live={summary.live_scenes:>4}  "
        f"excluded={summary.excluded_scenes:>4}  "
        f"({summary.exclusion_pct:5.1f}% excluded)"
    )
    lines.append(
        f"duration:  total={summary.total_ms/1000:7.1f}s  "
        f"live={summary.live_total_ms/1000:7.1f}s  "
        f"longest_block={summary.longest_live_block_ms/1000:7.1f}s"
    )
    lines.append(f"live_blocks: {summary.live_block_count}")
    for i, b in enumerate(blocks):
        lines.append(
            f"  [{i}] {b.start_ms/1000:7.1f}s → {b.end_ms/1000:7.1f}s  "
            f"({b.duration_ms/1000:6.1f}s, {b.scene_count:>3} scenes)"
        )
    return "\n".join(lines)


def _render_json(video_id: str, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    blocks = partition_live_blocks(scenes)
    summary = summarize(scenes, blocks)
    return {
        "video_id": video_id,
        "summary": {
            "total_scenes": summary.total_scenes,
            "live_scenes": summary.live_scenes,
            "excluded_scenes": summary.excluded_scenes,
            "live_block_count": summary.live_block_count,
            "total_ms": summary.total_ms,
            "live_total_ms": summary.live_total_ms,
            "longest_live_block_ms": summary.longest_live_block_ms,
            "exclusion_pct": round(summary.exclusion_pct, 2),
        },
        "blocks": [
            {
                "start_ms": b.start_ms,
                "end_ms": b.end_ms,
                "duration_ms": b.duration_ms,
                "scene_count": b.scene_count,
                "scene_ids": list(b.scene_ids),
            }
            for b in blocks
        ],
    }


async def main_async(args: argparse.Namespace) -> int:
    org_id = await _resolve_org_id(args.org)
    if org_id is None:
        print(f"org slug not found: {args.org!r}", file=sys.stderr)
        return 2

    client = SceneSearchClient()
    try:
        results = []
        for video_id in args.video_ids:
            scenes = await _fetch_all_scenes(client, org_id, video_id)
            if args.json:
                results.append(_render_json(video_id, scenes))
            else:
                print(_render_text(video_id, scenes))
                print()
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
    finally:
        await client.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--org", required=True, help="org slug (e.g. devorg, livenow)")
    ap.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON instead of text"
    )
    ap.add_argument("video_ids", nargs="+", help="one or more drive video_ids (gd_…)")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
