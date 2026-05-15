"""Tier B storyboard picker — pure-function over already-scored chunks.

Algorithm:

  1. HOOK   — max ``hook_score`` chunk in the EARLIEST segment.
  2. INTRO  — earliest unused chunk whose transcript contains the
              ``llm_label`` or any ``spoken_alias`` AND whose
              ``importance_score`` ≥ INTRO_IMPORTANCE_FLOOR. Falls
              back to "any label-matching chunk" if no chunk clears
              the importance floor.
  3. CTA    — latest unused chunk in the LATEST segment with
              ``has_cta=True``. Falls back to max-hook in last 1/3
              of the chronological chunk list when no explicit CTA
              chunk exists.
  4. DETAIL — top-1-or-2 unused chunks by ``importance_score``,
              chronologically ordered, filling the DETAIL budget.

No LLM calls — operates entirely on the pre-computed
``ScoredChunk[]``. Tier C's ``LlmStoryboardPicker`` will replace
this picker via the same Protocol; the rest of the pipeline doesn't
change.

Determinism: input → output is deterministic for a given chunk
list and label set. Used-set tiebreaker is the chunk's
``start_ms`` (earlier wins). Tests pin known inputs to known
outputs to detect drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
from uuid import UUID

from app.logging_config import get_logger
from app.modules.shorts_auto_product.track_stt.models import (
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    SLOT_ORDER,
    SlotBudgets,
    SlotRole,
    StoryboardFragment,
    StoryboardPlan,
)

# structlog so kwargs reach the JSON formatter; stdlib ``extra=`` was
# silently dropped on staging (2026-05-07 finding — only event names
# rendered, hobbling slot-fill diagnostics).
logger = get_logger(__name__)


# Importance floor for the INTRO slot — chunks below this still get
# considered if NO chunk clears the floor (the fallback path).
# Picked at 0.6 because the LLM scorer's prompt explicitly defines
# importance as "introduces the product/category, explains
# benefits..." → 0.6 is the rough split point in calibration data.
INTRO_IMPORTANCE_FLOOR = 0.6

# Slot to track which third of the chronological chunk list the
# CTA fallback considers. 2/3 = "last third" — the CTA should sit
# in the closing portion of the source video, not the middle.
_CTA_FALLBACK_TAIL_FRACTION = 2.0 / 3.0

# Cap on DETAIL fragments. >2 fragments make the DETAIL section
# feel like a montage rather than a coherent demo. The chunk_scorer
# bounds chunks at 30s, so 2 × 30s caps DETAIL at 60s — already
# beyond the default DETAIL_MS=25_000 budget.
_DETAIL_MAX_FRAGMENTS = 2


@dataclass
class HeuristicStoryboardPicker:
    """Concrete implementation of the ``StoryboardPicker`` protocol.

    Stateless once instantiated — ``assemble`` is a pure function over
    its arguments. ``budgets`` is held as instance state only so
    service.py can construct it from settings once and reuse for all
    children of a scan_order.
    """

    budgets: SlotBudgets = field(default_factory=SlotBudgets)

    async def assemble(
        self,
        *,
        all_chunks: list[ScoredChunk],
        segments: list[MentionSegment],
        target_duration_ms: int,
        llm_label: str,
        spoken_aliases: list[str],
        org_id: UUID | None = None,  # noqa: ARG002 — protocol shape
    ) -> StoryboardPlan:
        if not all_chunks or not segments:
            logger.info(
                "stt_storyboard_empty_input",
                chunk_count=len(all_chunks),
                segment_count=len(segments),
            )
            return StoryboardPlan(
                fragments=[],
                total_duration_ms=0,
                slots_filled=set(),
                fallbacks_used=["empty_input"],
            )

        chronological = sorted(all_chunks, key=lambda c: c.start_ms)
        used_keys: set[tuple[int, int]] = set()
        fragments: list[StoryboardFragment] = []
        fallbacks: list[str] = []

        # Storyboard order: HOOK → INTRO → DETAIL → CTA, but we PICK
        # in HOOK → INTRO → CTA → DETAIL order so that DETAIL's
        # candidate set excludes everything claimed by the others.
        # (DETAIL has the loosest selection criteria, so it can
        # absorb whatever's left.)

        # ── 1. HOOK ─────────────────────────────────────────────────
        hook_chunk = self._pick_hook(
            chronological=chronological,
            earliest_segment=segments[0],
            used_keys=used_keys,
        )
        if hook_chunk is not None:
            fragments.append(self._make_fragment(
                chunk=hook_chunk,
                role=SlotRole.HOOK,
                rationale=f"max_hook_score={hook_chunk.score.hook_score:.2f}",
            ))
            used_keys.add(_chunk_key(hook_chunk))
        else:
            fallbacks.append("no_hook_candidate")

        # ── 2. INTRO ────────────────────────────────────────────────
        intro_chunk, intro_fallback = self._pick_intro(
            chronological=chronological,
            llm_label=llm_label,
            spoken_aliases=spoken_aliases,
            used_keys=used_keys,
        )
        if intro_chunk is not None:
            rationale = (
                f"first_label_match_imp={intro_chunk.score.importance_score:.2f}"
                if intro_fallback is None
                else f"intro_fallback={intro_fallback}"
            )
            fragments.append(self._make_fragment(
                chunk=intro_chunk, role=SlotRole.INTRO, rationale=rationale,
            ))
            used_keys.add(_chunk_key(intro_chunk))
            if intro_fallback is not None:
                fallbacks.append(intro_fallback)
        else:
            fallbacks.append("no_intro_candidate")

        # ── 3. CTA ──────────────────────────────────────────────────
        cta_chunk, cta_fallback = self._pick_cta(
            chronological=chronological,
            latest_segment=segments[-1],
            used_keys=used_keys,
        )
        if cta_chunk is not None:
            rationale = (
                "has_cta_latest"
                if cta_fallback is None
                else f"cta_fallback={cta_fallback} hook={cta_chunk.score.hook_score:.2f}"
            )
            fragments.append(self._make_fragment(
                chunk=cta_chunk, role=SlotRole.CTA, rationale=rationale,
            ))
            used_keys.add(_chunk_key(cta_chunk))
            if cta_fallback is not None:
                fallbacks.append(cta_fallback)
        else:
            fallbacks.append("no_cta_candidate")

        # ── 4. DETAIL ───────────────────────────────────────────────
        detail_fragments = self._pick_detail(
            chronological=chronological, used_keys=used_keys,
        )
        if not detail_fragments:
            fallbacks.append("no_detail_candidate")
        fragments.extend(detail_fragments)

        # ── 5. Sort into storyboard order ───────────────────────────
        # HOOK → INTRO → DETAIL[chrono] → CTA. Stable sort: same-role
        # ties break on source_start_ms so DETAIL fragments stay in
        # source-chronological order among themselves.
        fragments.sort(key=lambda f: (SLOT_ORDER[f.role], f.source_start_ms))

        slots_filled = {f.role for f in fragments}
        total_duration_ms = sum(f.actual_duration_ms for f in fragments)

        logger.info(
            "stt_storyboard_assembled",
            fragment_count=len(fragments),
            slots_filled=sorted(s.value for s in slots_filled),
            fallbacks_used=fallbacks,
            total_duration_ms=total_duration_ms,
            target_duration_ms=target_duration_ms,
            segment_count=len(segments),
            chunk_count=len(all_chunks),
        )

        return StoryboardPlan(
            fragments=fragments,
            total_duration_ms=total_duration_ms,
            slots_filled=slots_filled,
            fallbacks_used=fallbacks,
        )

    # ---------- per-slot pickers ----------

    def _pick_hook(
        self,
        *,
        chronological: list[ScoredChunk],
        earliest_segment: MentionSegment,
        used_keys: set[tuple[int, int]],
    ) -> ScoredChunk | None:
        """Max ``hook_score`` chunk in the earliest segment's window."""
        candidates = [
            c for c in chronological
            if (
                earliest_segment.start_ms <= c.start_ms
                and c.start_ms < earliest_segment.end_ms
                and _chunk_key(c) not in used_keys
            )
        ]
        if not candidates:
            return None
        # ``max`` ties broken by start_ms (earlier wins) for
        # deterministic output. Sort first, then pick max — relies
        # on Python's stable sort.
        candidates.sort(key=lambda c: c.start_ms)
        return max(candidates, key=lambda c: c.score.hook_score)

    def _pick_intro(
        self,
        *,
        chronological: list[ScoredChunk],
        llm_label: str,
        spoken_aliases: list[str],
        used_keys: set[tuple[int, int]],
    ) -> tuple[ScoredChunk | None, str | None]:
        """Earliest label-matching chunk above the importance floor.

        Returns ``(chunk, fallback_marker)`` where ``fallback_marker``
        is a short string for telemetry when the picker had to relax
        the criteria.
        """
        tokens = [t.casefold() for t in [llm_label, *spoken_aliases] if t and t.strip()]
        if not tokens:
            # Defensive: catalog entry should always carry a label.
            return None, None

        # Pass 1: importance >= floor AND label match
        for c in chronological:
            if _chunk_key(c) in used_keys:
                continue
            if c.score.importance_score < INTRO_IMPORTANCE_FLOOR:
                continue
            text_low = (c.text or "").casefold()
            if any(t in text_low for t in tokens):
                return c, None

        # Pass 2: any label match (lower importance bar)
        for c in chronological:
            if _chunk_key(c) in used_keys:
                continue
            text_low = (c.text or "").casefold()
            if any(t in text_low for t in tokens):
                return c, "intro_low_importance"

        return None, None

    def _pick_cta(
        self,
        *,
        chronological: list[ScoredChunk],
        latest_segment: MentionSegment,
        used_keys: set[tuple[int, int]],
    ) -> tuple[ScoredChunk | None, str | None]:
        """Explicit CTA chunk → fallback to high-hook in tail third.

        Returns ``(chunk, fallback_marker)``.
        """
        # Pass 1: explicit ``has_cta`` chunk inside the latest segment.
        explicit = [
            c for c in chronological
            if (
                latest_segment.start_ms <= c.start_ms
                and c.start_ms < latest_segment.end_ms
                and c.score.has_cta
                and _chunk_key(c) not in used_keys
            )
        ]
        if explicit:
            # Latest in time wins — CTA sits at the end of the clip.
            explicit.sort(key=lambda c: c.start_ms)
            return explicit[-1], None

        # Pass 2: max ``hook_score`` in the last 1/3 of chronological
        # chunks. "Hook near the end" is the closest substitute for
        # urgency when no explicit CTA exists.
        if not chronological:
            return None, None
        tail_idx = int(len(chronological) * _CTA_FALLBACK_TAIL_FRACTION)
        tail = [
            c for c in chronological[tail_idx:]
            if _chunk_key(c) not in used_keys
        ]
        if not tail:
            return None, None
        tail.sort(key=lambda c: c.start_ms)
        return max(tail, key=lambda c: c.score.hook_score), "cta_no_explicit_picks_tail_max_hook"

    def _pick_detail(
        self,
        *,
        chronological: list[ScoredChunk],
        used_keys: set[tuple[int, int]],
    ) -> list[StoryboardFragment]:
        """Top remaining chunks by importance, chronologically ordered.

        Caps at ``_DETAIL_MAX_FRAGMENTS``. The DETAIL budget is
        divided evenly across selected chunks so a chunk that only
        contributes 10s doesn't crowd out a stronger one.
        """
        candidates = [
            c for c in chronological
            if _chunk_key(c) not in used_keys
        ]
        if not candidates:
            return []

        # Top-K by importance, ties on start_ms (earlier wins).
        candidates.sort(key=lambda c: (-c.score.importance_score, c.start_ms))
        selected = candidates[:_DETAIL_MAX_FRAGMENTS]

        # Sort selected back to chronological order for storyboard
        # presentation — DETAIL plays in source-time order so the
        # narrative flows.
        selected.sort(key=lambda c: c.start_ms)

        per_fragment_budget = self.budgets.detail_ms // max(1, len(selected))
        return [
            self._make_fragment(
                chunk=c,
                role=SlotRole.DETAIL,
                rationale=f"detail_imp={c.score.importance_score:.2f}",
                budget_override_ms=per_fragment_budget,
            )
            for c in selected
        ]

    # ---------- fragment construction ----------

    def _make_fragment(
        self,
        *,
        chunk: ScoredChunk,
        role: SlotRole,
        rationale: str,
        budget_override_ms: int | None = None,
    ) -> StoryboardFragment:
        """Build a fragment by clamping the chunk's source range to
        the slot budget. The chunk's start_ms is preserved; end_ms is
        the earlier of (chunk.end_ms, start_ms + budget).
        """
        slot_budget = (
            budget_override_ms if budget_override_ms is not None
            else self.budgets.for_role(role)
        )
        chunk_duration = chunk.end_ms - chunk.start_ms
        actual_duration = min(chunk_duration, slot_budget)
        return StoryboardFragment(
            role=role,
            source_start_ms=chunk.start_ms,
            source_end_ms=chunk.start_ms + actual_duration,
            target_duration_ms=slot_budget,
            chunk_score=chunk.score,
            rationale=rationale,
        )


# ---------- internals ----------


def _chunk_key(chunk: ScoredChunk) -> tuple[int, int]:
    """Stable identity for the used-set. ``ScoredChunk`` is a frozen
    dataclass and hashable, but its hash includes ``text`` (a
    potentially-long string). ``(start_ms, end_ms)`` is sufficient
    because chunks within a single picker call are distinct by
    their non-overlapping time ranges.
    """
    return (chunk.start_ms, chunk.end_ms)


def _ms_window_overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Helper for tests; not used by production code yet."""
    return a_start < b_end and a_end > b_start


__all__ = [
    "HeuristicStoryboardPicker",
    "INTRO_IMPORTANCE_FLOOR",
]
