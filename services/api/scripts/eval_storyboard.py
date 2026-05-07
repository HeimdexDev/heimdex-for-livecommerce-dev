"""Evaluation harness for the auto-shorts storyboard picker.

Loads JSON fixtures with hand-labelled "ideal storyboards", runs the
chosen picker against the same scored-chunks + segments inputs, and
reports per-fixture metrics: slot fill rate, multi-segment recall,
storyboard ordering, and per-role IoU against the golden.

Manual / nightly only — NOT in CI. Mirrors the
``eval_shorts_auto_llm.py`` precedent: changing the picker (Tier
C swap-in, slot budget tweaks, scoring formula updates) must not
regress against the goldens.

Fixture format (``tests/shorts_auto_product/eval/goldens/storyboard/<name>.json``)::

    {
      "name": "korean_hairdryer_60s",
      "video_id": "gd_…",
      "llm_label": "달심",
      "spoken_aliases": ["이 드라이기"],
      "target_duration_ms": 60000,
      "scored_chunks": [
        {
          "start_ms": 0, "end_ms": 20000, "text": "달심 너무 좋아요",
          "hook_score": 0.9, "has_cta": false, "importance_score": 0.7
        },
        ...
      ],
      "segments": [
        {
          "start_ms": 0, "end_ms": 60000,
          "scenes": [
            {
              "scene_id": "gd_x_scene_001",
              "start_ms": 0, "end_ms": 20000,
              "transcript_text": "...", "speaker_transcript": "..."
            }
          ]
        }
      ],
      "ideal": {
        "hook":   {"source_start_ms": 0,     "source_end_ms": 8000},
        "intro":  {"source_start_ms": 20000, "source_end_ms": 32000},
        "detail": [
          {"source_start_ms": 40000, "source_end_ms": 52000}
        ],
        "cta":    {"source_start_ms": 80000, "source_end_ms": 88000}
      }
    }

Usage::

    cd services/api && source .venv/bin/activate
    python -m scripts.eval_storyboard \
        --fixtures tests/shorts_auto_product/eval/goldens/storyboard/ \
        [--picker heuristic] \
        [--out reports/storyboard_eval_$(date +%Y-%m-%d).json] \
        [--min-slot-fill-rate 0.75] [--min-iou 0.35]

Exit codes:
    0 — all fixtures pass quality gates
    1 — at least one regression
    2 — eval-runner error (bad fixture, missing file, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionedScene,
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard import (
    HeuristicStoryboardPicker,
    SlotBudgets,
    SlotRole,
    StoryboardPlan,
)


# ---------- fixture loading ----------


def _load_fixture(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    required = ("name", "scored_chunks", "segments", "target_duration_ms",
                "llm_label", "ideal")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"fixture {path}: missing keys {missing}")
    return data


def _to_scored_chunks(raw: list[dict[str, Any]]) -> list[ScoredChunk]:
    out: list[ScoredChunk] = []
    for r in raw:
        score = ChunkScore(
            hook_score=float(r["hook_score"]),
            has_cta=bool(r["has_cta"]),
            importance_score=float(r["importance_score"]),
        )
        out.append(ScoredChunk(
            start_ms=int(r["start_ms"]),
            end_ms=int(r["end_ms"]),
            text=str(r.get("text", "")),
            score=score,
        ))
    return out


def _to_segments(raw: list[dict[str, Any]]) -> list[MentionSegment]:
    out: list[MentionSegment] = []
    for s in raw:
        scenes = [
            MentionedScene(
                scene_id=str(sc["scene_id"]),
                start_ms=int(sc["start_ms"]),
                end_ms=int(sc["end_ms"]),
                score=1.0,
                matched_field="transcript_raw",
                matched_aliases=[],
                transcript_text=str(sc.get("transcript_text", "")),
                caption_text=str(sc.get("caption_text", "")),
                speaker_transcript=str(sc.get("speaker_transcript", "")),
            )
            for sc in s["scenes"]
        ]
        out.append(MentionSegment(
            start_ms=int(s["start_ms"]),
            end_ms=int(s["end_ms"]),
            scenes=scenes,
        ))
    return out


# ---------- metrics ----------


def _interval_iou(
    a_start: int, a_end: int, b_start: int, b_end: int,
) -> float:
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter / union if union > 0 else 0.0


def _per_role_iou(
    plan: StoryboardPlan, ideal: dict[str, Any],
) -> dict[str, float]:
    """For each role in ``ideal``, compare the plan's fragment IoU.

    DETAIL is a list in goldens (storyboard may have 1-2); we use
    the best-pair matching by IoU. Other roles map 1:1.
    """
    actuals: dict[str, list[tuple[int, int]]] = {
        SlotRole.HOOK.value: [],
        SlotRole.INTRO.value: [],
        SlotRole.DETAIL.value: [],
        SlotRole.CTA.value: [],
    }
    for f in plan.fragments:
        actuals[f.role.value].append((f.source_start_ms, f.source_end_ms))

    results: dict[str, float] = {}
    for role in (SlotRole.HOOK, SlotRole.INTRO, SlotRole.CTA):
        ideal_role = ideal.get(role.value)
        if not ideal_role:
            continue
        actual_intervals = actuals[role.value]
        if not actual_intervals:
            results[role.value] = 0.0
            continue
        a_start, a_end = actual_intervals[0]
        results[role.value] = _interval_iou(
            a_start, a_end,
            int(ideal_role["source_start_ms"]),
            int(ideal_role["source_end_ms"]),
        )

    # DETAIL: list-of-intervals on both sides; use mean of best
    # 1:1 pairings.
    ideal_detail = ideal.get(SlotRole.DETAIL.value, [])
    actual_detail = actuals[SlotRole.DETAIL.value]
    if ideal_detail and actual_detail:
        pair_ious = []
        for i_start_end in ideal_detail:
            best = 0.0
            for a_start, a_end in actual_detail:
                iou = _interval_iou(
                    a_start, a_end,
                    int(i_start_end["source_start_ms"]),
                    int(i_start_end["source_end_ms"]),
                )
                best = max(best, iou)
            pair_ious.append(best)
        results[SlotRole.DETAIL.value] = (
            sum(pair_ious) / len(pair_ious) if pair_ious else 0.0
        )

    return results


def _slot_fill_rate(plan: StoryboardPlan, ideal: dict[str, Any]) -> float:
    expected = sum(1 for r in (
        SlotRole.HOOK.value, SlotRole.INTRO.value,
        SlotRole.DETAIL.value, SlotRole.CTA.value,
    ) if ideal.get(r))
    if expected == 0:
        return 1.0
    actual = sum(
        1 for r in plan.slots_filled
        if ideal.get(r.value)
    )
    return actual / expected


def _multi_segment_recall(
    plan: StoryboardPlan, segments: list[MentionSegment],
) -> bool:
    """True when fragments span ≥2 distinct source segments. The
    "no random cut" success criteria — a clip pulled from one tight
    20s window is the failure mode the storyboard is supposed to
    eliminate.
    """
    if len(segments) < 2:
        return True  # ground truth has only one segment; vacuously true
    used_segment_indices: set[int] = set()
    for f in plan.fragments:
        for i, seg in enumerate(segments):
            if seg.start_ms <= f.source_start_ms < seg.end_ms:
                used_segment_indices.add(i)
                break
    return len(used_segment_indices) >= 2


def _ordering_correct(plan: StoryboardPlan) -> bool:
    """HOOK source_start_ms ≤ all other fragments'; CTA ≥ all
    others' (when CTA filled).
    """
    if not plan.fragments:
        return True
    by_role = {f.role: f for f in plan.fragments}
    if SlotRole.HOOK in by_role:
        hook_start = by_role[SlotRole.HOOK].source_start_ms
        for f in plan.fragments:
            if f.role != SlotRole.HOOK and f.source_start_ms < hook_start:
                return False
    if SlotRole.CTA in by_role:
        cta_start = by_role[SlotRole.CTA].source_start_ms
        for f in plan.fragments:
            if f.role != SlotRole.CTA and f.source_start_ms > cta_start:
                return False
    return True


# ---------- runner ----------


async def _run_fixture(
    *, fixture: dict[str, Any], picker_name: str,
    cache_dir: Path, refresh_cache: bool,
) -> dict[str, Any]:
    chunks = _to_scored_chunks(fixture["scored_chunks"])
    segments = _to_segments(fixture["segments"])

    if picker_name == "heuristic":
        picker = HeuristicStoryboardPicker(budgets=SlotBudgets())
    elif picker_name == "llm":
        # Tier C — LLM director. Plan
        # ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md``.
        # Eval uses a snapshot cache so reruns are deterministic and
        # offline. ``--refresh-cache`` re-fires the real OpenAI call
        # and overwrites the snapshot; default mode replays from disk.
        picker = _build_llm_picker_for_eval(
            fixture_name=str(fixture["name"]),
            cache_dir=cache_dir,
            refresh_cache=refresh_cache,
        )
    else:
        raise ValueError(f"unsupported picker '{picker_name}'")

    plan = await picker.assemble(
        all_chunks=chunks,
        segments=segments,
        target_duration_ms=int(fixture["target_duration_ms"]),
        llm_label=str(fixture["llm_label"]),
        spoken_aliases=list(fixture.get("spoken_aliases", [])),
        org_id=uuid4(),
    )

    return {
        "name": fixture["name"],
        "picker": picker_name,
        "slot_fill_rate": _slot_fill_rate(plan, fixture["ideal"]),
        "multi_segment_recall": _multi_segment_recall(plan, segments),
        "ordering_correct": _ordering_correct(plan),
        "per_role_iou": _per_role_iou(plan, fixture["ideal"]),
        "fallbacks_used": plan.fallbacks_used,
        "fragment_count": len(plan.fragments),
        "fragments": [
            {
                "role": f.role.value,
                "source_start_ms": f.source_start_ms,
                "source_end_ms": f.source_end_ms,
                "rationale": f.rationale,
            }
            for f in plan.fragments
        ],
    }


# ---------- Tier C / LLM picker eval shim ----------
#
# Snapshot cache for the eval harness. Live LLM calls during eval
# would be slow + non-deterministic + costly to repeat; the cache
# makes goldens reproducible offline. Default mode replays cached
# responses; ``--refresh-cache`` re-fires real calls.
#
# Cache layout::
#
#   tests/shorts_auto_product/eval/llm_cache/<prompt_version>/<fixture_name>.json
#
# The file holds the LLM's raw JSON response body (the
# ``message.content`` string). Bumping ``llm_prompt.PROMPT_VERSION``
# silently invalidates the cache by directory name — the eval will
# fail with "no snapshot for fixture X at prompt_version v2" and
# the runner re-fires with ``--refresh-cache`` to fill the new
# version's cache.


class _SnapshotChatCompletions:
    """Mimics ``openai.AsyncOpenAI().chat.completions``.

    On ``create()`` reads the cached JSON response body for the
    given fixture; if missing AND ``refresh_cache=True`` will issue
    the real OpenAI call and write the response to disk; otherwise
    raises ``FileNotFoundError`` so the picker's exception handler
    falls back to the heuristic (which is what we want — eval surface
    a "missing snapshot" without crashing the run).
    """

    def __init__(
        self,
        *,
        cache_path: Path,
        refresh: bool,
        real_client: Any | None,
    ) -> None:
        self._cache_path = cache_path
        self._refresh = refresh
        self._real_client = real_client

    async def create(self, **kwargs: Any) -> Any:
        if self._refresh:
            if self._real_client is None:
                raise RuntimeError(
                    "--refresh-cache requires OPENAI_API_KEY to be set "
                    "in the environment so the eval can fire real calls"
                )
            response = await self._real_client.chat.completions.create(**kwargs)
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(
                    {
                        "content": response.choices[0].message.content,
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return response
        # Replay-only path
        if not self._cache_path.exists():
            raise FileNotFoundError(
                f"no snapshot at {self._cache_path}; run with "
                "--refresh-cache to populate"
            )
        snap = json.loads(self._cache_path.read_text(encoding="utf-8"))
        return _SimpleResponse(
            content=snap["content"],
            prompt_tokens=int(snap.get("prompt_tokens", 1250)),
            completion_tokens=int(snap.get("completion_tokens", 300)),
        )


class _SnapshotChat:
    def __init__(self, completions: _SnapshotChatCompletions) -> None:
        self.completions = completions


class _SnapshotOpenAIClient:
    """Drop-in for ``openai.AsyncOpenAI`` exposing only the surface
    the picker uses (``client.chat.completions.create``)."""

    def __init__(
        self,
        *,
        cache_path: Path,
        refresh: bool,
        real_client: Any | None,
    ) -> None:
        self.chat = _SnapshotChat(
            _SnapshotChatCompletions(
                cache_path=cache_path,
                refresh=refresh,
                real_client=real_client,
            ),
        )


class _SimpleResponse:
    """Minimal ``response`` object the picker consumes."""

    def __init__(
        self, *, content: str, prompt_tokens: int, completion_tokens: int,
    ) -> None:
        self.choices = [_SimpleChoice(content)]
        self.usage = _SimpleUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        )


class _SimpleChoice:
    def __init__(self, content: str) -> None:
        self.message = _SimpleMessage(content)


class _SimpleMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _SimpleUsage:
    def __init__(self, *, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


def _build_llm_picker_for_eval(
    *, fixture_name: str, cache_dir: Path, refresh_cache: bool,
) -> Any:
    """Construct an ``LlmStoryboardPicker`` whose OpenAI client reads
    from / writes to the snapshot cache.

    The cache is keyed on ``PROMPT_VERSION`` so a prompt edit (which
    bumps the version) invalidates by directory rather than silently
    serving stale snapshots.
    """
    # Lazy-import so the heuristic-only eval path doesn't pay the
    # OpenAI SDK import cost.
    import os

    from app.lib.whisper_transcribe.budget import InMemoryBudgetTracker
    from app.modules.shorts_auto_product.track_stt.storyboard.heuristic_picker import (
        HeuristicStoryboardPicker as _HeuristicForEval,
    )
    from app.modules.shorts_auto_product.track_stt.storyboard.llm_picker import (
        LlmStoryboardPicker,
    )
    from app.modules.shorts_auto_product.track_stt.storyboard.llm_prompt import (
        PROMPT_VERSION,
    )

    cache_path = cache_dir / PROMPT_VERSION / f"{fixture_name}.json"

    real_client: Any | None = None
    if refresh_cache:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "--refresh-cache requires OPENAI_API_KEY in the environment"
            )
        # Lazy import — only when actually refreshing.
        from openai import AsyncOpenAI  # type: ignore[import-not-found]

        real_client = AsyncOpenAI(api_key=api_key)

    snapshot_client = _SnapshotOpenAIClient(
        cache_path=cache_path,
        refresh=refresh_cache,
        real_client=real_client,
    )

    return LlmStoryboardPicker(
        openai_client=snapshot_client,
        model="gpt-4o-mini",
        prompt_version=PROMPT_VERSION,
        timeout_s=15.0,  # generous for eval; production uses 5s
        budgets=SlotBudgets(),
        # Eval doesn't enforce a real budget — set high so a refresh
        # run on N fixtures isn't artificially capped.
        budget_tracker=InMemoryBudgetTracker(daily_budget_usd=100.0),
        fallback=_HeuristicForEval(budgets=SlotBudgets()),
    )


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"fixture_count": 0}
    fill = [r["slot_fill_rate"] for r in results]
    multi = sum(1 for r in results if r["multi_segment_recall"])
    order_ok = sum(1 for r in results if r["ordering_correct"])
    all_ious: list[float] = []
    for r in results:
        all_ious.extend(r["per_role_iou"].values())
    return {
        "fixture_count": len(results),
        "mean_slot_fill_rate": statistics.fmean(fill) if fill else 0.0,
        "multi_segment_recall_pct": multi / len(results) if results else 0.0,
        "ordering_correct_pct": order_ok / len(results) if results else 0.0,
        "mean_iou": statistics.fmean(all_ious) if all_ious else 0.0,
    }


# ---------- entrypoint ----------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fixtures", type=Path, required=True,
        help="directory of .json fixture files",
    )
    p.add_argument(
        "--picker", choices=("heuristic", "llm"), default="heuristic",
        help=(
            "which picker to evaluate. 'llm' replays from the snapshot "
            "cache by default; pass --refresh-cache to re-fire real "
            "OpenAI calls"
        ),
    )
    p.add_argument(
        "--cache-dir", type=Path,
        default=Path("tests/shorts_auto_product/eval/llm_cache"),
        help=(
            "snapshot cache root (LLM picker only). Cache files keyed "
            "as <cache-dir>/<prompt_version>/<fixture_name>.json"
        ),
    )
    p.add_argument(
        "--refresh-cache", action="store_true",
        help=(
            "re-fire real OpenAI calls and overwrite snapshots "
            "(LLM picker only). Costs ~$0.0004 per fixture; explicit "
            "knob — default mode is replay-only"
        ),
    )
    p.add_argument(
        "--out", type=Path, default=None,
        help="optional path to write the report JSON",
    )
    p.add_argument(
        "--min-slot-fill-rate", type=float, default=0.75,
        help="quality gate; below this the run exits 1",
    )
    p.add_argument(
        "--min-iou", type=float, default=0.35,
        help="quality gate on mean per-role IoU",
    )
    return p.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    args = _parse_args(argv)
    fixtures_dir: Path = args.fixtures
    if not fixtures_dir.is_dir():
        print(
            f"fatal: fixtures dir not found: {fixtures_dir}", file=sys.stderr,
        )
        return 2
    fixture_paths = sorted(fixtures_dir.glob("*.json"))
    if not fixture_paths:
        print(
            f"fatal: no .json fixtures in {fixtures_dir}", file=sys.stderr,
        )
        return 2

    results: list[dict[str, Any]] = []
    for path in fixture_paths:
        try:
            fixture = _load_fixture(path)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"fatal: bad fixture {path}: {e}", file=sys.stderr)
            return 2
        result = await _run_fixture(
            fixture=fixture, picker_name=args.picker,
            cache_dir=args.cache_dir, refresh_cache=args.refresh_cache,
        )
        results.append(result)

    aggregate = _aggregate(results)
    report = {
        "picker": args.picker,
        "aggregate": aggregate,
        "fixtures": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Quality gates
    if aggregate["mean_slot_fill_rate"] < args.min_slot_fill_rate:
        print(
            f"REGRESSION: mean_slot_fill_rate "
            f"{aggregate['mean_slot_fill_rate']:.2f} < gate "
            f"{args.min_slot_fill_rate}",
            file=sys.stderr,
        )
        return 1
    if aggregate["mean_iou"] < args.min_iou:
        print(
            f"REGRESSION: mean_iou {aggregate['mean_iou']:.2f} "
            f"< gate {args.min_iou}",
            file=sys.stderr,
        )
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
