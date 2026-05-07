"""Tier C storyboard picker — LLM director over scored chunks.

Plan: ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md``.

Calls gpt-4o-mini once per scan with the chronologically-indexed
chunk list + product context, asks it to pick HOOK / INTRO /
DETAIL / CTA fragments by chunk index, and validates the response
in three layers (OpenAI strict-mode JSON schema → Pydantic →
semantic constraints). Any defect at any layer falls back to
``HeuristicStoryboardPicker`` (Tier B).

Coupling:

* Imports ``app.lib.whisper_transcribe.budget`` for the
  ``BudgetTracker`` Protocol + ``InMemoryBudgetTracker`` (the
  ``app/lib/`` location makes this share-able; do NOT import from
  ``app.modules.shorts_auto.llm.budget`` per the cross-feature
  loose-coupling rule).
* Imports the heuristic picker as a fallback, satisfying the
  three-layer-resilience contract documented in
  ``picker_protocol.py``.
* Does NOT import ``composition_builder``, ``service.py``, or
  anything from ``shorts_render``. The Protocol is the only seam.

Cost shape:
* ~1250 input tokens × $0.15/1M = $0.000188
* ~300 output tokens × $0.60/1M = $0.000180
* Per call: ~$0.0004 (escalation budget reservation: $0.001 to
  give headroom for occasional larger inputs).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.lib.whisper_transcribe.budget import (
    BudgetExceededError as _BudgetExceededError,
    BudgetTracker as _BudgetTracker,
)
from app.logging_config import get_logger
from app.modules.shorts_auto_product.track_stt.models import (
    MentionSegment,
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard.heuristic_picker import (
    HeuristicStoryboardPicker,
)
from app.modules.shorts_auto_product.track_stt.storyboard.llm_prompt import (
    PROMPT_VERSION as _MODULE_PROMPT_VERSION,
    _SYSTEM_PROMPT,
    build_user_prompt,
)
from app.modules.shorts_auto_product.track_stt.storyboard.llm_schemas import (
    _RESPONSE_JSON_SCHEMA,
    _LlmFragmentPick,
    _LlmPlanResponse,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    SLOT_ORDER,
    SlotBudgets,
    SlotRole,
    StoryboardFragment,
    StoryboardPlan,
)


logger = get_logger(__name__)


# Reserved per call. Slightly above the typical $0.0004 to absorb
# token-count variance from particularly long Korean transcripts.
# ``record(actual_cost)`` after the call rebalances against this
# reservation.
_RESERVATION_USD = 0.001


# Hard floor: 1× HOOK + 1× INTRO + 1× CTA + 1× DETAIL = 4 unique
# chunks needed to satisfy the schema without reuse. Below this the
# picker early-exits to heuristic without firing the LLM call.
_MIN_CHUNKS_FOR_LLM = 4

# Threshold below which the prompt nudges the LLM to use 1× DETAIL
# only. With 4 chunks total and 1× DETAIL, all 4 are unique. Two
# DETAILs would require 5 unique chunks.
_SMALL_CHUNK_HINT_BELOW = 5

# Cap on chunks fed to the LLM per call. Prompt size scales with
# this; staging spot-check 2026-05-08 saw 128-142 chunks on a
# 66-min source video → ~6500 input tokens → 10s+ timeouts and
# the LLM losing track of "last third" with that many candidates.
# 20 is empirically large enough for narrative quality (chunk_scorer
# bounds chunks at 30s, so 20 chunks ≈ 5-10 min of speech) and
# small enough for sub-3s gpt-4o-mini latency.
_MAX_CHUNKS_TO_LLM = 20

# Chunks per third when capping. ``HOOK_CANDIDATES_PER_THIRD`` from
# first third (high hook_score), ``CTA_CANDIDATES_PER_THIRD`` from
# last (has_cta=True preferred), DETAIL fills the rest by
# importance.
_HOOK_CANDIDATES_PER_THIRD = 5
_CTA_CANDIDATES_PER_THIRD = 5


# gpt-4o-mini pricing (USD per 1M tokens). See
# https://openai.com/api/pricing/ — bump in lockstep with model
# changes. Wrapped in a ``_cost_from_usage`` helper so test fixtures
# can pin known costs.
_MODEL_PRICING_USD_PER_M = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Escalation target if eval ever shows Tier B > Tier C.
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


@dataclass
class LlmStoryboardPicker:
    """Tier C concrete implementation of ``StoryboardPicker``.

    Stateless once instantiated — ``assemble`` is the entry point.
    ``fallback`` is held as instance state so the heuristic budgets
    are configured once per scan_order at factory time.
    """

    openai_client: Any  # AsyncOpenAI — typed as Any to avoid SDK import at module load
    model: str
    prompt_version: str
    timeout_s: float
    budgets: SlotBudgets
    budget_tracker: _BudgetTracker
    fallback: HeuristicStoryboardPicker
    _reservation_usd: float = field(default=_RESERVATION_USD, init=False)

    async def assemble(
        self,
        *,
        all_chunks: list[ScoredChunk],
        segments: list[MentionSegment],
        target_duration_ms: int,
        llm_label: str,
        spoken_aliases: list[str],
        org_id: UUID | None = None,
    ) -> StoryboardPlan:
        """Pick fragments via the LLM. Falls back to Tier B on any defect.

        Picker NEVER raises out — Protocol contract guarantee. Every
        defect path logs structured + delegates to the heuristic.
        """
        # ── 0. PROMPT_VERSION drift check (warn loud, do not block) ──
        if self.prompt_version != _MODULE_PROMPT_VERSION:
            logger.warning(
                "stt_storyboard_llm_prompt_version_drift",
                env_version=self.prompt_version,
                module_version=_MODULE_PROMPT_VERSION,
                resolution="using module value at runtime; eval cache may be invalidated",
            )

        # ── 1. Empty input — short-circuit to fallback ──
        if not all_chunks or not segments:
            logger.info(
                "stt_storyboard_llm_skipped",
                reason="empty_input",
                chunk_count=len(all_chunks),
                segment_count=len(segments),
                picker="llm",
            )
            return await self.fallback.assemble(
                all_chunks=all_chunks,
                segments=segments,
                target_duration_ms=target_duration_ms,
                llm_label=llm_label,
                spoken_aliases=spoken_aliases,
                org_id=org_id,
            )

        # ── 1b. Insufficient chunks — schema-impossible ──
        # 1× HOOK + 1× INTRO + 1× CTA + 1× DETAIL = 4 unique chunks
        # required. Below this the LLM has no path to a valid plan
        # and would either reuse a chunk_index (Pydantic rejects) or
        # the request would be wasted budget.
        if len(all_chunks) < _MIN_CHUNKS_FOR_LLM:
            logger.info(
                "stt_storyboard_llm_skipped",
                reason="insufficient_chunks",
                chunk_count=len(all_chunks),
                min_required=_MIN_CHUNKS_FOR_LLM,
                picker="llm",
            )
            return await self.fallback.assemble(
                all_chunks=all_chunks,
                segments=segments,
                target_duration_ms=target_duration_ms,
                llm_label=llm_label,
                spoken_aliases=spoken_aliases,
                org_id=org_id,
            )

        # ── 2. Budget reservation ──
        try:
            self.budget_tracker.check_and_reserve(self._reservation_usd)
        except _BudgetExceededError as e:
            logger.info(
                "stt_storyboard_llm_skipped",
                reason="budget_exceeded",
                error=str(e),
                picker="llm",
            )
            return await self.fallback.assemble(
                all_chunks=all_chunks,
                segments=segments,
                target_duration_ms=target_duration_ms,
                llm_label=llm_label,
                spoken_aliases=spoken_aliases,
                org_id=org_id,
            )

        # ── 3. Build prompt + call OpenAI ──
        # Cap chunks to keep prompt size bounded — without this, a
        # 60-min source video produces 100+ chunks (~6500 input
        # tokens) and gpt-4o-mini either times out OR loses track
        # of "last third" with that many candidates (staging
        # 2026-05-08 finding). The selected subset preserves
        # temporal coverage so HOOK / INTRO / CTA all have viable
        # picks, but the LLM gets a manageable list.
        chronological_full = sorted(all_chunks, key=lambda c: c.start_ms)
        chronological = _select_chunks_for_prompt(
            chronological=chronological_full,
            cap=_MAX_CHUNKS_TO_LLM,
        )
        small_hint = len(chronological) < _SMALL_CHUNK_HINT_BELOW

        user_prompt = build_user_prompt(
            all_chunks=chronological,
            target_duration_ms=target_duration_ms,
            llm_label=llm_label,
            spoken_aliases=spoken_aliases,
            slot_budgets=self.budgets,
            small_chunk_hint=small_hint,
        )
        seed = _stable_seed(llm_label=llm_label, prompt_version=self.prompt_version)

        logger.info(
            "stt_storyboard_llm_request",
            chunk_count=len(chronological),
            chunk_count_pre_cap=len(chronological_full),
            small_chunk_hint=small_hint,
            target_duration_ms=target_duration_ms,
            model=self.model,
            prompt_version=self.prompt_version,
            picker="llm",
        )

        try:
            response = await asyncio.wait_for(
                self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": _RESPONSE_JSON_SCHEMA,
                    },
                    temperature=0.0,
                    seed=seed,
                ),
                timeout=self.timeout_s,
            )
        except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001 — see comment
            # We deliberately catch ``Exception`` (not just OpenAI-typed
            # exceptions) so an unrelated SDK upgrade exposing new
            # exception classes doesn't bring down the picker. Tier B
            # fallback is the safety net; loud structured log is the
            # diagnostic. The ``# noqa: BLE001`` documents the choice.
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "stt_storyboard_llm_skipped",
                reason="api_failure",
                error_class=type(exc).__name__,
                error=str(exc)[:200],
                picker="llm",
            )
            return await self.fallback.assemble(
                all_chunks=all_chunks,
                segments=segments,
                target_duration_ms=target_duration_ms,
                llm_label=llm_label,
                spoken_aliases=spoken_aliases,
                org_id=org_id,
            )

        # ── 4. Parse + validate (Pydantic + semantic) ──
        try:
            content = _extract_response_content(response)
            plan_response = _LlmPlanResponse.model_validate_json(content)
            _validate_semantic_constraints(plan_response, chronological)
        except (ValidationError, ValueError, KeyError, AttributeError) as exc:
            self.budget_tracker.release_reservation(self._reservation_usd)
            logger.warning(
                "stt_storyboard_llm_skipped",
                reason="validation_failed",
                error_class=type(exc).__name__,
                error=str(exc)[:300],
                picker="llm",
            )
            return await self.fallback.assemble(
                all_chunks=all_chunks,
                segments=segments,
                target_duration_ms=target_duration_ms,
                llm_label=llm_label,
                spoken_aliases=spoken_aliases,
                org_id=org_id,
            )

        # ── 5. Map chunk_index → ScoredChunk → StoryboardFragment ──
        fragments = [
            _make_fragment(
                pick=pick,
                chunk=chronological[pick.chunk_index],
                budgets=self.budgets,
            )
            for pick in plan_response.fragments
        ]
        # Storyboard order: HOOK → INTRO → DETAIL[chrono] → CTA.
        fragments.sort(key=lambda f: (SLOT_ORDER[f.role], f.source_start_ms))

        # ── 6. Record cost + emit success log ──
        cost_usd = _cost_from_usage(response, model=self.model)
        self.budget_tracker.record(cost_usd)
        slots_filled = {f.role for f in fragments}
        total_duration_ms = sum(f.actual_duration_ms for f in fragments)

        logger.info(
            "stt_storyboard_llm_response",
            cost_usd=cost_usd,
            fragment_count=len(fragments),
            slots_filled=sorted(s.value for s in slots_filled),
            total_duration_ms=total_duration_ms,
            target_duration_ms=target_duration_ms,
            global_rationale=(plan_response.global_rationale or "")[:200],
            prompt_version=self.prompt_version,
            picker="llm",
        )

        return StoryboardPlan(
            fragments=fragments,
            total_duration_ms=total_duration_ms,
            slots_filled=slots_filled,
            fallbacks_used=[],
        )


# ────────────────────────── helpers ──────────────────────────


def _stable_seed(*, llm_label: str, prompt_version: str) -> int:
    """Deterministic 32-bit seed.

    Hashed on ``(llm_label, prompt_version)`` so the same product +
    same prompt version → same OpenAI seed → same picks (modulo
    OpenAI's checkpoint-level non-determinism, which is unavoidable).

    Mirrors ``shorts_auto.scorers.llm._stable_seed`` and
    ``chunk_scorer.py``'s seeding strategy.
    """
    key = f"{llm_label}|{prompt_version}".encode()
    digest = hashlib.sha1(key).digest()
    return int.from_bytes(digest[:4], "big")


def _extract_response_content(response: Any) -> str:
    """Pull the JSON content string out of an OpenAI chat completion
    response. Centralized so the SDK shape is captured in one place;
    if OpenAI rev's the response shape we adjust here, not in 6
    error-handling sites.
    """
    return response.choices[0].message.content


def _cost_from_usage(response: Any, *, model: str) -> float:
    """Compute USD cost from response.usage.

    Falls back to ``_RESERVATION_USD`` on any defect — overpaying the
    budget is preferable to underpaying (which would let the budget
    drift past its real ceiling).
    """
    pricing = _MODEL_PRICING_USD_PER_M.get(model)
    if pricing is None:
        return _RESERVATION_USD
    try:
        usage = response.usage
        in_cost = (usage.prompt_tokens / 1_000_000.0) * pricing["input"]
        out_cost = (usage.completion_tokens / 1_000_000.0) * pricing["output"]
        return in_cost + out_cost
    except (AttributeError, TypeError):
        return _RESERVATION_USD


_ROLE_STRING_TO_ENUM: dict[str, SlotRole] = {
    "hook": SlotRole.HOOK,
    "intro": SlotRole.INTRO,
    "detail": SlotRole.DETAIL,
    "cta": SlotRole.CTA,
}


def _make_fragment(
    *,
    pick: _LlmFragmentPick,
    chunk: ScoredChunk,
    budgets: SlotBudgets,
) -> StoryboardFragment:
    """Translate one LLM-derived pick + the resolved ``ScoredChunk``
    into a ``StoryboardFragment``.

    Clamps the fragment's source range to the slot budget — same
    logic as ``HeuristicStoryboardPicker._make_fragment``. For DETAIL
    we use the FULL detail_ms budget per fragment when only one
    DETAIL was picked; if two, the picker's caller (this module) lets
    each fragment claim its full chunk duration up to ``detail_ms``
    — concatenation in composition_builder still respects the total
    target_duration.
    """
    role = _ROLE_STRING_TO_ENUM[pick.role]
    slot_budget = budgets.for_role(role)
    chunk_duration = chunk.end_ms - chunk.start_ms
    actual_duration = min(chunk_duration, slot_budget)
    return StoryboardFragment(
        role=role,
        source_start_ms=chunk.start_ms,
        source_end_ms=chunk.start_ms + actual_duration,
        target_duration_ms=slot_budget,
        chunk_score=chunk.score,
        rationale=pick.rationale,
    )


def _select_chunks_for_prompt(
    *,
    chronological: list[ScoredChunk],
    cap: int,
) -> list[ScoredChunk]:
    """Cap the chunk list passed to the LLM with temporal coverage.

    When the source has more chunks than ``cap``, naively passing all
    of them inflates the prompt + slows the response + confuses the
    LLM about temporal placement (staging 2026-05-08 finding —
    128-chunk prompts produced CTA picks in the first third). This
    helper selects a representative subset:

      * From the FIRST third: top-K by ``hook_score`` (HOOK candidates).
      * From the LAST  third: chunks with ``has_cta=True`` first, then
        top by ``hook_score`` (CTA candidates).
      * From the MIDDLE third: top-K by ``importance_score``
        (DETAIL/INTRO candidates).
      * Padding: if any third runs out of distinctive chunks, fill
        from the residual pool by composite score.

    Returns chunks sorted CHRONOLOGICALLY (the order the prompt and
    the LLM's chunk_index responses depend on).

    Pure function — no I/O, no logging.
    """
    n = len(chronological)
    if n <= cap:
        return list(chronological)

    # Source duration anchors the third boundaries.
    source_duration = max(c.end_ms for c in chronological)
    first_cutoff = source_duration // 3
    last_cutoff = (source_duration * 2) // 3

    first_third = [c for c in chronological if c.start_ms < first_cutoff]
    middle_third = [
        c for c in chronological
        if first_cutoff <= c.start_ms < last_cutoff
    ]
    last_third = [c for c in chronological if c.start_ms >= last_cutoff]

    selected: dict[tuple[int, int], ScoredChunk] = {}

    def _key(c: ScoredChunk) -> tuple[int, int]:
        return (c.start_ms, c.end_ms)

    # First third — HOOK candidates by hook_score, then importance.
    for c in sorted(
        first_third, key=lambda c: (-c.score.hook_score, -c.score.importance_score),
    )[:_HOOK_CANDIDATES_PER_THIRD]:
        selected[_key(c)] = c

    # Last third — has_cta first (sorted by start_ms so latest CTA wins
    # when multiple), then high hook_score.
    cta_chunks = sorted(
        [c for c in last_third if c.score.has_cta], key=lambda c: -c.start_ms,
    )
    for c in cta_chunks[:_CTA_CANDIDATES_PER_THIRD]:
        selected[_key(c)] = c
    # Backfill last third with high hook_score chunks.
    remaining_last = [
        c for c in last_third if _key(c) not in selected
    ]
    for c in sorted(remaining_last, key=lambda c: -c.score.hook_score)[
        : _CTA_CANDIDATES_PER_THIRD - sum(
            1 for c in cta_chunks[:_CTA_CANDIDATES_PER_THIRD]
        )
    ]:
        selected[_key(c)] = c

    # Middle third — DETAIL/INTRO candidates by importance.
    middle_budget = max(0, cap - len(selected))
    for c in sorted(
        middle_third,
        key=lambda c: (-c.score.importance_score, -c.composite),
    )[:middle_budget]:
        selected[_key(c)] = c

    # If we still have headroom (e.g., short source where middle is
    # tiny), backfill from the global pool by composite score so we
    # don't return fewer chunks than the cap allows when more were
    # available.
    if len(selected) < cap:
        residual = [c for c in chronological if _key(c) not in selected]
        residual.sort(key=lambda c: -c.composite)
        for c in residual:
            if len(selected) >= cap:
                break
            selected[_key(c)] = c

    out = list(selected.values())
    out.sort(key=lambda c: c.start_ms)
    return out


def _validate_semantic_constraints(
    plan: _LlmPlanResponse,
    chronological: list[ScoredChunk],
) -> None:
    """Constraints that need ``chronological`` as context.

    Pydantic's ``_LlmPlanResponse`` already enforces:
      * Slot count rules (1× HOOK, 1× INTRO, 1× CTA, 1-2× DETAIL).
      * No chunk_index reuse.

    This function adds:
      * ``chunk_index`` in bounds.
      * HOOK chunk's ``start_ms`` ≤ 1/3 × source duration.
      * CTA chunk's ``start_ms`` ≥ 2/3 × source duration.
      * DETAIL fragments are chronologically ordered relative to each
        other.
      * HOOK < INTRO < CTA in ``start_ms`` (loose role-temporal
        ordering — INTRO can sit anywhere between HOOK's chunk start
        and CTA's chunk start).

    Raises ``ValueError`` on any violation.
    """
    n = len(chronological)
    # Bounds check
    for f in plan.fragments:
        if f.chunk_index >= n:
            raise ValueError(
                f"chunk_index {f.chunk_index} out of bounds (n={n})"
            )

    # Source duration = end_ms of the latest chunk. Used to anchor the
    # first/last-third constraints.
    source_duration = max(c.end_ms for c in chronological)
    first_third_cutoff = source_duration // 3
    last_third_cutoff = (source_duration * 2) // 3

    by_role: dict[str, list[_LlmFragmentPick]] = {}
    for f in plan.fragments:
        by_role.setdefault(f.role, []).append(f)

    hook_pick = by_role["hook"][0]
    intro_pick = by_role["intro"][0]
    cta_pick = by_role["cta"][0]

    hook_start = chronological[hook_pick.chunk_index].start_ms
    intro_start = chronological[intro_pick.chunk_index].start_ms
    cta_start = chronological[cta_pick.chunk_index].start_ms

    if hook_start > first_third_cutoff:
        raise ValueError(
            f"HOOK chunk start_ms={hook_start}ms past first-third cutoff "
            f"={first_third_cutoff}ms (source_duration={source_duration}ms)"
        )
    if cta_start < last_third_cutoff:
        raise ValueError(
            f"CTA chunk start_ms={cta_start}ms before last-third cutoff "
            f"={last_third_cutoff}ms (source_duration={source_duration}ms)"
        )

    # Loose temporal ordering: HOOK < INTRO < CTA on chunk start_ms.
    if not (hook_start < intro_start < cta_start):
        raise ValueError(
            f"role temporal order broken: hook_start={hook_start} "
            f"intro_start={intro_start} cta_start={cta_start} "
            f"(must satisfy hook < intro < cta)"
        )

    # DETAIL fragments must be chronologically ordered if there are 2.
    detail_picks = by_role.get("detail", [])
    if len(detail_picks) == 2:
        d0 = chronological[detail_picks[0].chunk_index].start_ms
        d1 = chronological[detail_picks[1].chunk_index].start_ms
        # Order in the LLM response array doesn't have to match
        # chronology — we'll re-sort. But the two DETAIL chunks must
        # be DIFFERENT in time (`>=` instead of `>` because Pydantic
        # already rejected duplicate chunk_index).
        if d0 == d1:
            raise ValueError(
                f"both DETAIL fragments share start_ms={d0}"
            )


__all__ = [
    "LlmStoryboardPicker",
]
