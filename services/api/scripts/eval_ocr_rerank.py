"""Evaluation harness for the OCR re-rank in mention_extractor.

Compares the BM25 candidate set under flag=False (transcript+caption
only — today's behavior) vs flag=True (adds ocr_text_norm clauses) on
real OS data. Used to:
  1. Validate the flag-on path lifts catalog-entry recall vs flag-off.
  2. Tune ocr_boost (sweep 0.4 / 0.6 / 0.8 / 1.0).
  3. Surface per-entry rank shifts so we can eyeball whether the
     promoted-by-OCR scenes plausibly show the product.

Manual / nightly only — NOT in CI. Mirrors ``eval_storyboard.py`` and
``eval_shorts_auto_llm.py``. Plan:
``.claude/plans/ocr-mention-extractor-rerank.md``.

Runs INSIDE the api container (needs OS + Postgres access via the
existing app.modules.* code paths).

Usage::

    # On staging:
    ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63
    cd /opt/heimdex/dev-heimdex-for-livecommerce
    docker compose exec -T api python -m scripts.eval_ocr_rerank \\
        --catalog-org devorg \\
        [--ocr-boost 0.6] \\
        [--out /tmp/ocr_rerank_eval.json]

    # Or to sweep boost values:
    for b in 0.4 0.6 0.8 1.0; do
      docker compose exec -T api python -m scripts.eval_ocr_rerank \\
        --catalog-org devorg --ocr-boost $b \\
        --out /tmp/ocr_rerank_eval_b${b}.json
    done

Outputs (markdown to stdout, optional JSON to --out):
  - Aggregate: total catalog entries evaluated, baseline recall,
    treatment recall, candidates added by OCR, candidates lost by OCR
    (should be 0 — strict-additive).
  - Per-entry: baseline_count, treatment_count, top-K agreement,
    novel-OCR scenes (in treatment but not baseline), top-1 changed.
  - Top movers: catalog entries that gained / lost the most rank
    positions for their best scene.

Exit codes:
    0 — eval ran successfully (whether or not OCR helps; this is
        a measurement tool, not a gate)
    1 — strict-additive guarantee violated (treatment lost a
        baseline-matched scene). This MUST be 0; if not, the patch
        is broken.
    2 — eval-runner error (DB unreachable, missing arg, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, asdict
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.config import get_settings
from app.db.base import get_async_session_factory
from app.modules.shorts_auto_product.track_stt import mention_extractor


# ---------- types ----------


@dataclass
class CatalogProbe:
    """One (video_id, catalog_entry) pair to eval."""

    video_id: str  # gd_*
    org_id: UUID
    catalog_entry_id: UUID
    llm_label: str
    spoken_aliases: list[str]


@dataclass
class EntryResult:
    """Eval result for one catalog probe."""

    video_id: str
    label: str
    aliases_count: int

    baseline_count: int
    treatment_count: int

    # Scene IDs in baseline (transcript+caption only) ranked
    baseline_scene_ids: list[str]
    # Scene IDs in treatment (with OCR clauses)
    treatment_scene_ids: list[str]

    # Diff
    novel_in_treatment: list[str]  # OCR-driven gains
    lost_in_treatment: list[str]  # MUST be empty (strict-additive)

    # Quality signals
    top1_changed: bool
    top5_jaccard: float  # 0.0-1.0
    ocr_match_count_treatment: int


# ---------- DB / OS plumbing ----------


async def _load_catalog_probes(org_slug: str) -> list[CatalogProbe]:
    """Pull (video_id, catalog_entry) pairs from Postgres for the
    given org. Restricts to videos with keyframes (otherwise OCR
    won't have run on them anyway)."""
    sf = get_async_session_factory()
    async with sf() as s:
        rows = (
            await s.execute(
                text(
                    """
                    SELECT df.video_id AS vid,
                           df.org_id AS org_id,
                           pce.id AS catalog_entry_id,
                           pce.llm_label AS label,
                           pce.spoken_aliases AS aliases
                    FROM product_catalog_entries pce
                    JOIN drive_files df ON df.id = pce.video_id
                    JOIN orgs o ON o.id = df.org_id
                    WHERE pce.rejected_at IS NULL
                      AND df.keyframe_s3_prefix IS NOT NULL
                      AND df.is_deleted = false
                      AND o.slug = :slug
                    ORDER BY df.video_id, pce.llm_label
                    """
                ),
                {"slug": org_slug},
            )
        ).all()
    return [
        CatalogProbe(
            video_id=r.vid,
            org_id=r.org_id,
            catalog_entry_id=r.catalog_entry_id,
            llm_label=r.label or "",
            spoken_aliases=list(r.aliases or []),
        )
        for r in rows
    ]


async def _build_os_client():
    """Construct an AsyncOpenSearch client from app config — same
    factory ``app.modules.search.client`` uses but lazy-imported here
    to keep this script's import surface narrow.

    NOTE on the loose-coupling rule: CLAUDE.md forbids
    ``shorts_auto_product`` from cross-importing other ``app.modules.*``
    packages. This script lives at ``services/api/scripts/`` (NOT inside
    ``app/modules/shorts_auto_product/``), so the rule applies to
    PRODUCTION module code that gets loaded by the API process — not
    to one-shot eval scripts run via ``python -m scripts.foo``.

    The production module ``track_stt/mention_extractor.py`` correctly
    constructs its OS client INLINE (see its module docstring) per the
    rule. This script's import of the same factory mirrors the
    ``eval_storyboard.py`` precedent and is acceptable as
    eval-tooling-only coupling.
    """
    from app.modules.search.client import get_opensearch_client  # noqa

    return get_opensearch_client()


# ---------- eval loop ----------


def _jaccard(a: list[str], b: list[str], k: int = 5) -> float:
    sa, sb = set(a[:k]), set(b[:k])
    if not sa and not sb:
        return 1.0
    union = len(sa | sb)
    if union == 0:
        return 1.0
    return len(sa & sb) / union


async def _eval_entry(
    *,
    probe: CatalogProbe,
    os_client: Any,
    index_alias: str,
    ocr_boost: float,
    result_cap: int = 5000,
) -> EntryResult:
    """Eval one catalog probe.

    Uses ``result_cap=5000`` instead of the production default (200) so
    the strict-additive check reflects QUERY SEMANTICS, not cap pressure.
    With a generous cap, treatment ⊇ baseline iff the OS query is truly
    strict-additive (which we want to verify — adding ``should`` clauses
    cannot exclude any doc that already matched without the new clauses).
    The 200-cap behavior is a separate consideration for production
    (re-ranking can bump baseline scenes out of the top-200 — that's
    the desired effect, not a regression).
    """
    baseline = await mention_extractor.find_mentioned_scenes(
        os_client=os_client,
        index_alias=index_alias,
        org_id=probe.org_id,
        video_id=probe.video_id,
        llm_label=probe.llm_label,
        spoken_aliases=probe.spoken_aliases,
        result_cap=result_cap,
        ocr_rerank_enabled=False,
        ocr_boost=ocr_boost,  # ignored when flag=False; passed for parity
    )
    treatment = await mention_extractor.find_mentioned_scenes(
        os_client=os_client,
        index_alias=index_alias,
        org_id=probe.org_id,
        video_id=probe.video_id,
        llm_label=probe.llm_label,
        spoken_aliases=probe.spoken_aliases,
        result_cap=result_cap,
        ocr_rerank_enabled=True,
        ocr_boost=ocr_boost,
    )

    base_ids = [s.scene_id for s in baseline]
    treat_ids = [s.scene_id for s in treatment]
    base_set = set(base_ids)
    treat_set = set(treat_ids)

    return EntryResult(
        video_id=probe.video_id,
        label=probe.llm_label,
        aliases_count=len(probe.spoken_aliases),
        baseline_count=len(base_ids),
        treatment_count=len(treat_ids),
        baseline_scene_ids=base_ids,
        treatment_scene_ids=treat_ids,
        novel_in_treatment=sorted(treat_set - base_set),
        lost_in_treatment=sorted(base_set - treat_set),
        top1_changed=(
            (base_ids[0] if base_ids else None)
            != (treat_ids[0] if treat_ids else None)
        ),
        top5_jaccard=_jaccard(base_ids, treat_ids, k=5),
        ocr_match_count_treatment=sum(1 for s in treatment if s.ocr_match),
    )


# ---------- aggregation + output ----------


def _format_markdown(
    results: list[EntryResult],
    *,
    org_slug: str,
    ocr_boost: float,
    index_alias: str,
) -> str:
    """Pretty-print the eval results to stdout."""
    n = len(results)
    if n == 0:
        return f"No catalog entries found for org={org_slug!r}.\n"

    base_match = sum(1 for r in results if r.baseline_count > 0)
    treat_match = sum(1 for r in results if r.treatment_count > 0)
    only_treat = sum(
        1 for r in results if r.treatment_count > 0 and r.baseline_count == 0
    )
    avg_baseline = sum(r.baseline_count for r in results) / n
    avg_treatment = sum(r.treatment_count for r in results) / n
    novel_total = sum(len(r.novel_in_treatment) for r in results)
    lost_total = sum(len(r.lost_in_treatment) for r in results)
    avg_top5_jaccard = sum(r.top5_jaccard for r in results) / n
    top1_changes = sum(1 for r in results if r.top1_changed)

    lines = []
    lines.append(f"# OCR re-rank eval — org={org_slug} ocr_boost={ocr_boost}")
    lines.append("")
    lines.append(f"index_alias: {index_alias}")
    lines.append(f"catalog entries evaluated: {n}")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append(f"  baseline match-rate (any candidate):  {base_match}/{n} = {100*base_match/n:.1f}%")
    lines.append(f"  treatment match-rate (any candidate): {treat_match}/{n} = {100*treat_match/n:.1f}%")
    lines.append(f"  treatment-only matches (OCR rescued): {only_treat}/{n} = {100*only_treat/n:.1f}%")
    lines.append(f"  avg candidate count (baseline):       {avg_baseline:.1f}")
    lines.append(f"  avg candidate count (treatment):      {avg_treatment:.1f}")
    lines.append(f"  delta avg candidate count:            +{avg_treatment - avg_baseline:.1f}")
    lines.append("")
    lines.append("## Query-strict-additive check (uncapped result set)")
    lines.append("")
    lines.append(f"  baseline scenes lost by treatment: {lost_total}  (MUST be 0)")
    if lost_total != 0:
        lines.append("  ❌ STRICT-ADDITIVE VIOLATED — the OS query body is excluding")
        lines.append("     scenes that matched without OCR clauses. This is a real bug:")
        lines.append("     adding ``should`` clauses can never reduce the matched-doc set.")
        lines.append("     Re-check ``_build_bm25_query`` for unintended ``must``/``filter``")
        lines.append("     additions on the OCR side.")
    else:
        lines.append("  ✅ Query-strict-additive holds: every scene matched by baseline")
        lines.append("     also matches under treatment (in the uncapped result set).")
    lines.append("")
    lines.append("  NOTE: production uses result_cap=200; OCR-promoted scenes can push")
    lines.append("  baseline-only scenes OUT of the top-200 in the production code path.")
    lines.append("  That's re-ranking working as designed, NOT a regression.")
    lines.append("")
    lines.append("## Quality signals")
    lines.append("")
    lines.append(f"  total scenes newly surfaced by OCR: {novel_total}")
    lines.append(f"  avg top-5 Jaccard (baseline ∩ treatment): {avg_top5_jaccard:.3f}")
    lines.append(f"  entries where top-1 scene changed:        {top1_changes}/{n}")
    lines.append("")
    lines.append("## Top movers (entries with most novel OCR scenes)")
    lines.append("")
    lines.append("| video_id | label | aliases | baseline | treatment | novel | top1_changed | top5_jaccard | ocr_match |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    sorted_by_novel = sorted(results, key=lambda r: -len(r.novel_in_treatment))
    for r in sorted_by_novel[:25]:
        lines.append(
            f"| {r.video_id} | {r.label!r} | {r.aliases_count} | "
            f"{r.baseline_count} | {r.treatment_count} | "
            f"{len(r.novel_in_treatment)} | {r.top1_changed} | "
            f"{r.top5_jaccard:.2f} | {r.ocr_match_count_treatment} |"
        )
    lines.append("")
    lines.append("## Per-video aggregate")
    lines.append("")
    by_video: dict[str, list[EntryResult]] = {}
    for r in results:
        by_video.setdefault(r.video_id, []).append(r)
    lines.append("| video_id | entries | base_match% | treat_match% | total_novel |")
    lines.append("|---|---|---|---|---|")
    for vid, ents in sorted(by_video.items()):
        n_ents = len(ents)
        bm = sum(1 for r in ents if r.baseline_count > 0)
        tm = sum(1 for r in ents if r.treatment_count > 0)
        nv = sum(len(r.novel_in_treatment) for r in ents)
        lines.append(
            f"| {vid} | {n_ents} | "
            f"{100*bm/n_ents:.0f}% | {100*tm/n_ents:.0f}% | {nv} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------- main ----------


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    index_alias = args.index_alias or "heimdex_scenes"

    print(f"[eval] loading catalog probes for org={args.catalog_org!r}...", file=sys.stderr)
    probes = await _load_catalog_probes(args.catalog_org)
    if not probes:
        print(f"[eval] no catalog probes for org={args.catalog_org}", file=sys.stderr)
        return 0
    print(f"[eval] {len(probes)} probes; ocr_boost={args.ocr_boost}", file=sys.stderr)

    os_client = await _build_os_client()
    try:
        results: list[EntryResult] = []
        for i, probe in enumerate(probes, 1):
            try:
                r = await _eval_entry(
                    probe=probe,
                    os_client=os_client,
                    index_alias=index_alias,
                    ocr_boost=args.ocr_boost,
                )
                results.append(r)
            except Exception as e:  # noqa: BLE001
                print(
                    f"[eval] probe {i}/{len(probes)} {probe.video_id} "
                    f"label={probe.llm_label!r} failed: {e}",
                    file=sys.stderr,
                )
                continue
            if i % 20 == 0:
                print(f"[eval] progress {i}/{len(probes)}", file=sys.stderr)
    finally:
        try:
            await os_client.close()
        except Exception:
            pass

    md = _format_markdown(
        results, org_slug=args.catalog_org, ocr_boost=args.ocr_boost, index_alias=index_alias,
    )
    print(md)

    if args.out:
        out_path = args.out
        from pathlib import Path
        Path(out_path).write_text(json.dumps(
            {
                "org_slug": args.catalog_org,
                "ocr_boost": args.ocr_boost,
                "index_alias": index_alias,
                "entries": [asdict(r) for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ))
        print(f"[eval] JSON written to {out_path}", file=sys.stderr)

    # Strict-additive gate
    lost_total = sum(len(r.lost_in_treatment) for r in results)
    if lost_total > 0:
        print(
            f"[eval] ❌ strict-additive violated: {lost_total} baseline scenes lost by treatment",
            file=sys.stderr,
        )
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OCR re-rank eval harness — compares find_mentioned_scenes "
        "with ocr_rerank_enabled=False vs True on real OS data."
    )
    parser.add_argument(
        "--catalog-org",
        required=True,
        help="Org slug (e.g., 'devorg'). Restricts to product_catalog_entries on this org.",
    )
    parser.add_argument(
        "--ocr-boost",
        type=float,
        default=0.6,
        help="Boost multiplier for OCR clauses (default: 0.6, matches the production default).",
    )
    parser.add_argument(
        "--index-alias",
        default=None,
        help="OS index alias (default: 'heimdex_scenes').",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional JSON output path. Markdown summary always goes to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 2


if __name__ == "__main__":
    sys.exit(main())
