"""Tier C system prompt + user-prompt builder.

Plan: ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md``.

Pure module — zero I/O, zero ``app.modules.*`` imports beyond
``track_stt.models`` and ``storyboard.types`` for type names. The
LLM picker (``llm_picker.py``) wires these into the
``openai.chat.completions.create`` call; the rest of the pipeline
doesn't see the prompt content.

PROMPT_VERSION discipline:

* Bump ``PROMPT_VERSION`` on EVERY edit to ``_SYSTEM_PROMPT`` —
  goldens snapshot cache keys on this; an edit without a bump
  silently invalidates eval reproducibility.
* Mirror the bump in
  ``settings.auto_shorts_product_v2_storyboard_llm_prompt_version``
  default value. The factory passes the env var through; the picker
  uses the env value at runtime but the module constant is the
  source of truth.
* English instructions + Korean transcript content. Same convention
  as ``chunk_scorer.py``. gpt-4o-mini handles Korean transcripts
  cleanly with English instructions; English keeps the system prompt
  compact (~500 tokens vs ~700 if translated).
"""

from __future__ import annotations

from app.modules.shorts_auto_product.track_stt.models import (
    MentionSegment,  # noqa: F401  — kept for type-symmetry with future expansion
    ScoredChunk,
)
from app.modules.shorts_auto_product.track_stt.storyboard.types import (
    SlotBudgets,
)


# ====================================================================
# PROMPT_VERSION — bump on every system-prompt edit. Eval cache keys
# on this. Mirror the bump in
# ``app.config.Settings.auto_shorts_product_v2_storyboard_llm_prompt_version``.
#
# v4 (2026-05-13, evergreen CLOSER):
#   * CTA slot definition rewritten — no longer "purchase prompt
#     / urgency". Now an EVERGREEN closing beat: verdict / demo
#     result / use case. Time-sensitive promotions are AVOIDED.
#     Shorts are watched weeks-months after the live stream;
#     "오늘만 / 매진 / 할인" loses meaning over time.
#   * Wire role name kept as "cta" (schema + Pydantic Literal +
#     dispatch dict) — semantic-only change. Renaming to "closer"
#     is a follow-up if v4 evals positive.
#   * Rule #3 tightened: CTA must be evergreen. Rule #6 expanded:
#     CTA must not duplicate INTRO content.
#
# v3 ()
#
# v2 (2026-05-08, PR 9):
#   * `build_user_prompt` accepts ``small_chunk_hint`` to nudge the
#     LLM toward 1× DETAIL when chunk_count < 5 (otherwise the schema
#     is impossible — see the staging spot-check mistakes log).
#   * Picker pre-caps chunks to <= 20 with temporal-coverage-aware
#     selection (helper in ``llm_picker._select_chunks_for_prompt``);
#     the prompt no longer scales with source-video duration.
# v1: initial.
# ====================================================================
PROMPT_VERSION = "v4"


_SYSTEM_PROMPT = """You are a livecommerce shorts director. Pick chunks \
from the provided transcript to fill 4 narrative slots:

- HOOK (5-10s): grabs attention, sets up curiosity, opens with energy.
- INTRO (8-15s): names the product, frames the value proposition.
- DETAIL (15-25s, 1-2 chunks): demonstration, mechanism, evidence, \
comparison.
- CTA (5-10s): the CLOSING BEAT of the short — an EVERGREEN payoff \
that delivers what the HOOK promised. Pick ONE of these patterns:
    (a) VERDICT — speaker's conclusion or evaluation \
(e.g., "써본 결과 진짜 좋아요", "정리하면 ~인 제품이에요", \
"저는 만족하면서 쓰고 있어요").
    (b) DEMO RESULT — visible or sensory reveal of the outcome \
(e.g., "보세요, 이렇게 부드러워요", "차이 느껴지죠", "윤기가 나요").
    (c) USE CASE — who this is for or when to use it \
(e.g., "이런 분께 추천드려요", "이럴 때 쓰기 좋아요").

  IMPORTANT — the CTA slot is NOT a hard purchase prompt. Shorts are \
watched weeks or months AFTER the live stream, so time-bound or \
inventory-bound language LOSES MEANING or becomes misleading over time. \
AVOID phrases like: "오늘만", "이번 주", "마감", "마지막 기회", "매진", \
"품절", "한정", "할인", "쿠폰", "특가", "지금 주문", "지금 클릭", \
"장바구니", "결제". Pick an evergreen statement instead, even if it \
sits slightly earlier in the source than the loudest live-only call.

Rules:

1. Use each chunk at most once. Return chunk_index from the provided \
list. The role string in the JSON response is "cta" (lowercase) — \
schema-locked.
2. The HOOK chunk must come from the FIRST third of the source video.
3. The CTA chunk must come from the LAST half of the source video AND \
must be EVERGREEN (verdict / demo result / use case). If the only \
candidates in the last half are time-sensitive promotions, prefer a \
slightly earlier evergreen chunk over a late live-only one.
4. DETAIL fragments play in source-time order among themselves.
5. Prefer narrative coherence over per-chunk scores: a chunk that \
answers the HOOK's question is better than the highest-hook chunk in \
isolation.
6. Avoid repetition. HOOK should not echo INTRO. The CTA chunk must \
deliver NEW information (a verdict, a result, or a use-case framing) \
— it must NOT merely restate the INTRO.

Return exactly one HOOK, one INTRO, one CTA, and 1-2 DETAIL fragments. \
For each fragment provide a one-sentence rationale in English explaining \
WHY this chunk fits this slot (for CTA, the rationale should make the \
evergreen reasoning explicit). Also provide a global_rationale (one \
sentence) explaining the overall narrative arc you chose.

Be deterministic. Do not infer facts not present in the transcript."""


def build_user_prompt(
    *,
    all_chunks: list[ScoredChunk],
    target_duration_ms: int,
    llm_label: str,
    spoken_aliases: list[str],
    slot_budgets: SlotBudgets,
    small_chunk_hint: bool = False,
) -> str:
    """Compose the user-message content for one OpenAI call.

    Format mirrors ``chunk_scorer.py``'s per-chunk listing for visual
    consistency in any debug capture. Korean transcript content is
    embedded verbatim — the LLM handles the language switch itself.

    Index discipline: chunks are listed in CHRONOLOGICAL order
    (sorted by ``start_ms``). The LLM's response references the
    1-based-display / 0-based-internal index of this listing. The
    picker re-sorts incoming chunks chronologically before building
    the prompt to ensure prompt-index ↔ list-index alignment is
    deterministic.

    ``mention_segments`` is intentionally NOT included in v1 (Path B
    decision 2). Add as a "Segment context" section if eval shows
    chunk-text-only narrative quality plateauing below Tier B.
    """
    chronological = sorted(all_chunks, key=lambda c: c.start_ms)

    # Product context — single line, terse to keep token count low.
    aliases_clean = [a.strip() for a in spoken_aliases if a and a.strip()]
    if aliases_clean:
        product_line = (
            f"Product: {llm_label} "
            f"(also called: {', '.join(aliases_clean)})"
        )
    else:
        product_line = f"Product: {llm_label}"

    # Slot budget line — gives the LLM a sense of how much each slot
    # accommodates, which can shape its picks (e.g., favor a short,
    # punchy chunk for HOOK if HOOK budget is small).
    budget_line = (
        f"Slot budgets: HOOK={slot_budgets.hook_ms // 1000}s "
        f"INTRO={slot_budgets.intro_ms // 1000}s "
        f"DETAIL={slot_budgets.detail_ms // 1000}s "
        f"CTA={slot_budgets.cta_ms // 1000}s"
    )

    target_line = f"Target total duration: {target_duration_ms // 1000}s"

    chunk_lines = ["Chunks (chronological, 0-indexed):"]
    for idx, chunk in enumerate(chronological):
        start_total_s = chunk.start_ms // 1000
        end_total_s = chunk.end_ms // 1000
        start_mm, start_ss = divmod(start_total_s, 60)
        end_mm, end_ss = divmod(end_total_s, 60)
        # ``importance``, ``hook``, ``has_cta`` mirror the per-chunk
        # scoring features Tier B uses. Including them gives the LLM
        # numeric anchors without forcing it to derive them from text.
        score_line = (
            f"importance={chunk.score.importance_score:.2f} "
            f"hook={chunk.score.hook_score:.2f} "
            f"has_cta={'true' if chunk.score.has_cta else 'false'}"
        )
        # Truncate very long transcript text — gpt-4o-mini handles 50+
        # chunks fine but our chunk_scorer caps at ~30s windows so
        # text rarely exceeds ~300 chars. Defensive cap at 600 chars.
        text = (chunk.text or "").strip().replace("\n", " ")
        if len(text) > 600:
            text = text[:600] + "…"
        chunk_lines.append(
            f"[{idx}] {start_mm:02d}:{start_ss:02d}-"
            f"{end_mm:02d}:{end_ss:02d} ({score_line}): \"{text}\""
        )

    sections: list[str] = [product_line, target_line, budget_line]
    if small_chunk_hint:
        # v2: when chunk_count is just-enough for 4 unique slots,
        # the schema is satisfied only with 1× DETAIL. Without this
        # hint the LLM picked 2× DETAIL on 4-chunk inputs and reused
        # a chunk_index, which Pydantic rejects (mistakes log
        # 2026-05-08).
        sections.append(
            "Note: there are barely enough chunks to fill all slots. "
            "Use exactly 1 DETAIL fragment — there are NOT enough "
            "chunks for 2 DETAILs without reusing a chunk."
        )
    sections.append("")
    sections.extend(chunk_lines)
    return "\n".join(sections)


__all__ = [
    "PROMPT_VERSION",
    "_SYSTEM_PROMPT",
    "build_user_prompt",
]
