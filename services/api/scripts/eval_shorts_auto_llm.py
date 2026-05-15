"""Evaluation harness for the shorts-auto LLM scorer.

Golden pattern: for each fixture video, we pre-compute (by hand or via a
prior accepted run) the "ideal" scene_id list that should appear in a
~60s short. This script runs the live LLM scorer against the same
fixtures and reports Jaccard overlap + ordered edit distance.

Gate: a new ``PROMPT_VERSION`` should not regress Jaccard below the
existing goldens' score. Run manually when changing ``prompt.py``; the
CI pytest suite intentionally does NOT run this (needs real OPENAI_API_KEY
and costs money).

Fixtures live at:
    tests/shorts_auto/eval/goldens/<video_id>.json
    {
      "video_id": "gd_...",
      "scene_corpus": [ { SceneDocument fields } ],
      "mode": "both",
      "ideal_scene_ids": ["gd_..._scene_001", "gd_..._scene_004", ...],
      "prompt_version": "2026-04-24-v1"
    }

Usage:
    OPENAI_API_KEY=sk-... python -m scripts.eval_shorts_auto_llm \
        --fixtures tests/shorts_auto/eval/goldens/ \
        --mode both \
        [--min-jaccard 0.5]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.modules.shorts_auto.llm.budget import InMemoryBudgetTracker
from app.modules.shorts_auto.llm.client import OpenAIClipClient
from app.modules.shorts_auto.scorers import ScoringContext
from app.modules.shorts_auto.scorers.llm import OpenAILLMScorer
from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.scorer import ScoringMode


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="eval_shorts_auto_llm")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/shorts_auto/eval/goldens"),
        help="Directory containing golden *.json fixtures.",
    )
    parser.add_argument(
        "--mode",
        choices=["human", "product", "both"],
        default="both",
        help="Override scoring mode (default: use fixture's mode).",
    )
    parser.add_argument(
        "--min-jaccard",
        type=float,
        default=0.5,
        help="Minimum acceptable Jaccard per fixture (exit 1 if any below).",
    )
    return parser.parse_args()


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


async def _run_one(fixture: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.openai_api_key
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is required for eval.")

    budget = InMemoryBudgetTracker(daily_budget_usd=5.0)
    client = OpenAIClipClient(
        api_key=api_key,
        model=settings.auto_shorts_llm_model,
        timeout_s=settings.auto_shorts_llm_timeout_sec,
        budget_tracker=budget,
    )
    scorer = OpenAILLMScorer(
        client=client,
        max_scenes=settings.auto_shorts_llm_max_scenes,
        prompt_version=fixture.get(
            "prompt_version", settings.auto_shorts_llm_prompt_version
        ),
    )

    corpus = [SceneDocument(**s) for s in fixture["scene_corpus"]]
    context = ScoringContext(
        mode=ScoringMode(fixture["mode"]),
        target_duration_sec=60,
        video_id=fixture["video_id"],
    )
    scored = await scorer.score(corpus, context)
    picked = [s.scene.scene_id for s in scored if s.breakdown.eligible]
    ideal = fixture["ideal_scene_ids"]

    return {
        "video_id": fixture["video_id"],
        "picked": picked,
        "ideal": ideal,
        "jaccard": _jaccard(picked, ideal),
    }


async def _main_async(args: argparse.Namespace) -> int:
    fixture_dir = args.fixtures
    if not fixture_dir.is_dir():
        print(f"No fixture dir at {fixture_dir}. Create some goldens first.")
        return 0

    fixture_files = sorted(fixture_dir.glob("*.json"))
    if not fixture_files:
        print(f"No fixtures in {fixture_dir}.")
        return 0

    results: list[dict[str, Any]] = []
    for path in fixture_files:
        fixture = json.loads(path.read_text())
        try:
            results.append(await _run_one(fixture))
        except Exception as e:
            print(f"FAIL {path.name}: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

    print("=" * 64)
    print(f"Eval results ({len(results)} fixtures)")
    print("=" * 64)
    failures = 0
    for r in results:
        marker = "✓" if r["jaccard"] >= args.min_jaccard else "✗"
        print(f"  {marker} {r['video_id']}: jaccard={r['jaccard']:.3f} "
              f"(picked {len(r['picked'])}, ideal {len(r['ideal'])})")
        if r["jaccard"] < args.min_jaccard:
            failures += 1
    mean_jaccard = sum(r["jaccard"] for r in results) / len(results)
    print(f"  Mean jaccard: {mean_jaccard:.3f}")
    return 1 if failures else 0


def main() -> int:
    _ = uuid4  # silence unused-import when no fixtures — uuid4 is imported for future expansion
    args = _parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
