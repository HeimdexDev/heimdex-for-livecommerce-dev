from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TypedDict, cast

from app.modules.search.eval import eval_summary_to_dict, run_search_evaluation
from app.modules.search.scene_client import SceneSearchClient


class CategorySummary(TypedDict):
    hit_at_10: float
    mrr_at_10: float
    count: int


class BaselineSummary(TypedDict):
    timestamp: str
    org_id: str
    config: dict[str, object]
    overall_hit_at_10: float
    overall_mrr_at_10: float
    per_category: dict[str, CategorySummary]
    negative_query_correct: bool


def _build_args() -> tuple[str | None, str]:
    parser = argparse.ArgumentParser(prog="run_search_eval")
    _ = parser.add_argument("--org-id", type=str, default=None)
    _ = parser.add_argument("--output-dir", type=str, default="../../artifacts/search-eval")
    parsed = parser.parse_args()
    return cast(str | None, parsed.org_id), cast(str, parsed.output_dir)


async def _detect_org_id(scene_client: SceneSearchClient) -> str:
    response: dict[str, object] = cast(
        dict[str, object],
        await scene_client.client.search(
            index=scene_client.index_name,
            body={"size": 1, "query": {"match_all": {}}, "_source": ["org_id"]},
        ),
    )
    hits_data = cast(dict[str, object], response.get("hits", {}))
    hits = cast(list[dict[str, object]], hits_data.get("hits", []))
    if not hits:
        raise RuntimeError("No scene documents found in OpenSearch index")
    source = cast(dict[str, object], hits[0].get("_source", {}))
    org_id = cast(str | None, source.get("org_id"))
    if not org_id:
        raise RuntimeError("First scene document does not contain org_id")
    return str(org_id)


def _print_summary_table(summary: BaselineSummary) -> None:
    print("\nSearch Eval Summary")
    print("=" * 72)
    print(f"Org ID: {summary['org_id']}")
    print(f"Timestamp: {summary['timestamp']}")
    print(f"Overall hit@10: {summary['overall_hit_at_10']:.4f}")
    print(f"Overall mrr@10: {summary['overall_mrr_at_10']:.4f}")
    print(f"Negative query correct (G15): {summary['negative_query_correct']}")
    print("\nPer-category")
    print(f"{'category':<16} {'count':>5} {'hit@10':>10} {'mrr@10':>10}")
    print("-" * 72)
    for category, metrics in summary["per_category"].items():
        print(
            f"{category:<16} {metrics['count']:>5} {metrics['hit_at_10']:>10.4f} {metrics['mrr_at_10']:>10.4f}"
        )


async def _run() -> int:
    org_id_arg, output_dir_arg = _build_args()
    output_dir = Path(output_dir_arg)
    output_dir.mkdir(parents=True, exist_ok=True)

    scene_client = SceneSearchClient()
    try:
        org_id = org_id_arg or await _detect_org_id(scene_client)
        summary = await run_search_evaluation(org_id=org_id, scene_client=scene_client)
        payload = eval_summary_to_dict(summary)

        baseline_path = output_dir / "baseline.json"
        baseline_summary_path = output_dir / "baseline_summary.json"

        with baseline_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        compact_summary: BaselineSummary = {
            "timestamp": cast(str, payload["timestamp"]),
            "org_id": cast(str, payload["org_id"]),
            "config": cast(dict[str, object], payload["config"]),
            "overall_hit_at_10": cast(float, payload["overall_hit_at_10"]),
            "overall_mrr_at_10": cast(float, payload["overall_mrr_at_10"]),
            "per_category": cast(dict[str, CategorySummary], payload["per_category"]),
            "negative_query_correct": cast(bool, payload["negative_query_correct"]),
        }
        with baseline_summary_path.open("w", encoding="utf-8") as f:
            json.dump(compact_summary, f, ensure_ascii=False, indent=2)

        _print_summary_table(compact_summary)
        print(f"\nWrote: {baseline_path}")
        print(f"Wrote: {baseline_summary_path}")
        return 0
    except Exception as exc:
        print(f"Search evaluation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        await scene_client.close()


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
