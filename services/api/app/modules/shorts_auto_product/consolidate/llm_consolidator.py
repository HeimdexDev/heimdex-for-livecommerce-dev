"""gpt-4o catalog consolidator with strict-JSON output.

Single LLM call that does TWO things in lockstep on the full active
catalog for one video:

1. **Merge duplicates.** Rows whose ``llm_label`` / ``spoken_aliases``
   refer to the same physical product collapse into one canonical row.
   Korean / branded labels win over English / generic forms.

2. **Filter non-sellable.** Rows whose label describes a host's tool
   (microphone, cup, hanger), an ambient prop, an on-screen graphic,
   or a bare generic English noun ("Bottle", "Box") get rejected.

Output is re-validated by an in-module checker: every input
``entry_id`` must appear exactly once across ``groups`` or
``rejections``, no hallucinated ids, canonical labels non-empty.
Failure → :class:`ConsolidationValidationError` and the orchestrator
short-circuits, leaving the raw catalog untouched.

Prompt is ported from the spike's ``pipeline/matcher.dedupe_vlm_labels``
where the rules were already calibrated on real livecommerce footage.
Two divergences from the spike:

* The input is keyed by ``entry_id`` (DB UUID), not bare label. The
  consolidator needs to know which specific row to merge or reject.
* ``is_sellable`` becomes a typed ``rejection.category`` (host_equipment,
  ambient_object, on_screen_graphic, generic_noun, placeholder) so we
  can surface a meaningful ``rejected_reason`` for debugging.

Loose-coupling: imports ONLY ``openai``, :mod:`app.config`,
:mod:`heimdex_media_contracts` shape constants where applicable, and
own-module symbols. No cross-imports from other ``app.modules.*``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.shorts_auto_product.consolidate.errors import (
    ConsolidationLLMError,
    ConsolidationValidationError,
)

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = "gpt-4o"
_DEFAULT_TIMEOUT_S = 120.0
# gpt-4o emits one decision per input row plus group bookkeeping.
# A 30-row catalog collapsing to ~10 canonicals + a handful of
# rejections fits comfortably under 4k tokens; 8k leaves headroom for
# the worst case (50 rows, every row in its own group, plus rejection
# reasoning).
_DEFAULT_MAX_OUTPUT_TOKENS = 8192

# Cost-per-million tokens (USD) for gpt-4o, 2026-04 pricing.
_GPT_4O_INPUT_USD_PER_M = 2.50
_GPT_4O_OUTPUT_USD_PER_M = 10.00
_GPT_4O_MINI_INPUT_USD_PER_M = 0.15
_GPT_4O_MINI_OUTPUT_USD_PER_M = 0.60


_REJECTION_CATEGORIES: frozenset[str] = frozenset({
    "host_equipment",     # microphone, camera, hanger, scissors host holds
    "ambient_object",     # background prop, studio furniture, decoration
    "on_screen_graphic",  # caption / banner / overlay text the VLM read
    "generic_noun",       # bare "Bottle", "Box", "Cup" with no brand
    "placeholder",        # "Product 1", "Cosmetic A", numbered/disjunctive
})


_RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "name": "catalog_consolidation_response",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["groups", "rejections"],
        "properties": {
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "canonical_entry_id",
                        "canonical_label",
                        "canonical_aliases",
                        "member_entry_ids",
                    ],
                    "properties": {
                        "canonical_entry_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "canonical_label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "canonical_aliases": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 20,
                        },
                        "member_entry_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "rejections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["entry_id", "category"],
                    "properties": {
                        "entry_id": {
                            "type": "string",
                            "minLength": 1,
                        },
                        "category": {
                            "type": "string",
                            "enum": sorted(_REJECTION_CATEGORIES),
                        },
                    },
                },
            },
        },
    },
}


_SYSTEM_PROMPT = (
    "You consolidate a per-video product catalog extracted from a "
    "Korean live commerce broadcast. Input is the union of two "
    "enumeration sources: vision (labels read off on-screen packaging) "
    "and STT (labels heard from the host's speech). Your output must "
    "make TWO decisions for every input row.\n"
    "\n"
    "DECISION A — MERGE duplicates into groups.\n"
    "  • Rows that refer to the same physical product collapse into "
    "ONE group with a single canonical row.\n"
    "  • Equivalence is case-INSENSITIVE and word-order-INSENSITIVE. "
    "Treat trailing words like ' product', ' item', ' package' as "
    "noise. Korean and English forms of the same brand/SKU are the "
    "same product (e.g. 'DALSIM 콜라겐' and '달심 콜라겐 부스터').\n"
    "  • The canonical_entry_id MUST be one of the input entry_ids in "
    "that group. Prefer the input row whose llm_label is most "
    "specific and most branded.\n"
    "  • canonical_label preference order: (1) Korean full product "
    "name with brand, (2) brand + Korean product noun (크림, 세럼, "
    "토너, 마스크, 클렌저, 부스터 등), (3) brand + specific English "
    "model name. Avoid bare English category words.\n"
    "  • canonical_aliases is the UNION of all rows' spoken_aliases in "
    "the group, deduplicated. Keep the user-spoken forms — they power "
    "later transcript search.\n"
    "  • member_entry_ids lists every input id in this group EXCEPT "
    "the canonical_entry_id itself.\n"
    "  • A row that is unique in the catalog and sellable still emits "
    "a group with member_entry_ids=[].\n"
    "\n"
    "DECISION B — REJECT non-sellable rows.\n"
    "Mark rows aggressively as rejected, choosing the most specific "
    "category:\n"
    "  • host_equipment — items the host holds for demonstration "
    "(microphone, camera, hanger, scissors, cup as a prop), or "
    "personal accessories like a ring/watch UNLESS jewelry is the "
    "category being sold.\n"
    "  • ambient_object — background props, studio furniture, "
    "decoration, plants, lighting equipment.\n"
    "  • on_screen_graphic — caption banners, price overlays, sticker "
    "graphics; the VLM read text from a graphic rather than a real "
    "product.\n"
    "  • generic_noun — bare English category words with no brand and "
    "no specificity: 'Bottle', 'Box', 'Bowl', 'Container', 'Plate', "
    "'Tube', 'Jar', 'Cup', 'Pack'. Also color-or-material + generic "
    "noun: 'red tube', 'white bowl', 'wooden coaster', 'transparent "
    "bowl'. A row with a real brand or Korean product noun is NOT "
    "generic_noun.\n"
    "  • placeholder — numbered, lettered, or disjunctive labels that "
    "indicate the model couldn't identify the product: 'Bottle 1', "
    "'Product A', 'Body wash or lotion bottle'.\n"
    "\n"
    "CONSERVATIVE PRINCIPLE — when in doubt, KEEP. Emit the row as "
    "its own group rather than rejecting. A false rejection (real "
    "product disappears from the gallery) is more costly than a false "
    "keep (an extra row the user can ignore).\n"
    "\n"
    "OUTPUT INVARIANT — every input entry_id MUST appear EXACTLY ONCE "
    "across the union of groups (canonical_entry_id or "
    "member_entry_ids) and rejections (entry_id). Do NOT invent ids "
    "that were not in the input."
)


@dataclass(frozen=True)
class ConsolidationGroup:
    """A canonical row plus the members it absorbs.

    ``member_entry_ids`` never includes ``canonical_entry_id``. An
    isolated row (its own canonical, no duplicates) has
    ``member_entry_ids == []``.
    """

    canonical_entry_id: UUID
    canonical_label: str
    canonical_aliases: list[str]
    member_entry_ids: list[UUID]


@dataclass(frozen=True)
class ConsolidationRejection:
    """One row marked non-sellable."""

    entry_id: UUID
    category: str  # one of _REJECTION_CATEGORIES


@dataclass(frozen=True)
class ConsolidationResult:
    """Pure-data result. The caller applies it via the catalog repo."""

    groups: list[ConsolidationGroup]
    rejections: list[ConsolidationRejection]
    cost_usd: float
    latency_ms: int
    model: str
    prompt_version: str
    raw_input_count: int


@dataclass(frozen=True)
class CatalogConsolidatorInput:
    """One row's worth of input for the LLM.

    Source / confidence / example_quote are passed through so the LLM
    can break ties when two rows look textually similar but one is a
    transcript artifact while the other is a vision-source row with a
    real crop.
    """

    entry_id: UUID
    llm_label: str
    spoken_aliases: list[str] = field(default_factory=list)
    source: str = "vision"
    confidence: float = 1.0
    example_quote: str | None = None


class CatalogConsolidator:
    """Single-shot catalog consolidator.

    Construct once per app process so the underlying ``AsyncOpenAI``
    connection pool is reused across requests. Stateless beyond the
    pool.
    """

    def __init__(
        self,
        *,
        openai_client: Any,
        model: str = _DEFAULT_MODEL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
        prompt_version: str = "v1.0",
    ) -> None:
        self._openai = openai_client
        self._model = model
        self._timeout_s = timeout_s
        self._max_output_tokens = max_output_tokens
        self._prompt_version = prompt_version

    @property
    def model(self) -> str:
        return self._model

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    async def consolidate(
        self,
        *,
        entries: list[CatalogConsolidatorInput],
    ) -> ConsolidationResult:
        """Run the consolidation LLM call and validate the response.

        Raises:
            :class:`ConsolidationLLMError`: timeout, OpenAI-side error,
                JSON parse failure.
            :class:`ConsolidationValidationError`: response parsed but
                referenced entry_ids that weren't in the input, or
                violated the exactly-once invariant.
        """
        if len(entries) <= 1:
            # Defensive — the orchestrator should skip the LLM entirely
            # for trivial catalogs. Returning an empty result lets us
            # keep this method total.
            return ConsolidationResult(
                groups=[],
                rejections=[],
                cost_usd=0.0,
                latency_ms=0,
                model=self._model,
                prompt_version=self._prompt_version,
                raw_input_count=len(entries),
            )

        messages = self._build_messages(entries=entries)
        input_id_set = {str(e.entry_id) for e in entries}

        start = time.monotonic()
        try:
            response = await self._openai.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": _RESPONSE_JSON_SCHEMA,
                },
                timeout=self._timeout_s,
                max_tokens=self._max_output_tokens,
            )
        except Exception as e:  # noqa: BLE001 — wrap-and-rethrow
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "consolidate_llm_call_failed",
                extra={
                    "model": self._model,
                    "latency_ms": latency_ms,
                    "input_count": len(entries),
                    "error": str(e)[:300],
                },
            )
            raise ConsolidationLLMError(
                f"OpenAI call failed: {e}",
            ) from e

        latency_ms = int((time.monotonic() - start) * 1000)
        usage = getattr(response, "usage", None)
        cost_usd = _estimate_cost_usd(usage, self._model)

        choice = response.choices[0]
        raw_content = choice.message.content
        try:
            payload = json.loads(raw_content or "{}")
        except json.JSONDecodeError as e:
            logger.warning(
                "consolidate_llm_json_decode_failed",
                extra={
                    "model": self._model,
                    "error": str(e)[:200],
                    "raw_preview": (raw_content or "")[:200],
                },
            )
            raise ConsolidationLLMError(
                f"LLM response is not valid JSON: {e}",
            ) from e

        groups, rejections = _validate_payload(
            payload=payload,
            input_id_set=input_id_set,
        )

        return ConsolidationResult(
            groups=groups,
            rejections=rejections,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            model=self._model,
            prompt_version=self._prompt_version,
            raw_input_count=len(entries),
        )

    def _build_messages(
        self,
        *,
        entries: list[CatalogConsolidatorInput],
    ) -> list[dict[str, Any]]:
        # Pass only the fields the LLM needs to decide. example_quote
        # is included for STT rows so the model can disambiguate
        # "host mentioned a placeholder noun once" from "real product".
        rows = [
            {
                "entry_id": str(e.entry_id),
                "llm_label": e.llm_label,
                "spoken_aliases": list(e.spoken_aliases or []),
                "source": e.source,
                "confidence": float(e.confidence),
                "example_quote": e.example_quote,
            }
            for e in entries
        ]
        user_payload = json.dumps(
            {"rows": rows}, ensure_ascii=False,
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ]


# ---------- pure helpers (testable in isolation) ----------


def _validate_payload(
    *,
    payload: dict[str, Any],
    input_id_set: set[str],
) -> tuple[list[ConsolidationGroup], list[ConsolidationRejection]]:
    """Validate the LLM response against the exactly-once invariant
    and entry_id authenticity.

    Returns parsed ``(groups, rejections)``. Raises
    :class:`ConsolidationValidationError` on any violation; the
    orchestrator treats that as "skip — leave raw catalog alone".
    """
    raw_groups = payload.get("groups")
    raw_rejections = payload.get("rejections")
    if not isinstance(raw_groups, list) or not isinstance(raw_rejections, list):
        raise ConsolidationValidationError(
            "response missing 'groups' or 'rejections' list",
        )

    seen: set[str] = set()
    groups: list[ConsolidationGroup] = []
    for raw_group in raw_groups:
        canonical_raw = str(raw_group.get("canonical_entry_id", "")).strip()
        canonical_label = str(raw_group.get("canonical_label", "")).strip()
        canonical_aliases_raw = raw_group.get("canonical_aliases") or []
        member_raw = raw_group.get("member_entry_ids") or []
        if not canonical_raw or canonical_raw not in input_id_set:
            raise ConsolidationValidationError(
                f"canonical_entry_id missing or unknown: {canonical_raw!r}",
            )
        if not canonical_label:
            raise ConsolidationValidationError(
                f"canonical_label is empty for group {canonical_raw!r}",
            )
        if canonical_raw in seen:
            raise ConsolidationValidationError(
                f"entry_id appears multiple times: {canonical_raw!r}",
            )
        seen.add(canonical_raw)
        member_ids: list[UUID] = []
        for raw_id in member_raw:
            sid = str(raw_id).strip()
            if sid == canonical_raw:
                # Spec says members exclude canonical. Tolerate the
                # LLM including it (harmless) by skipping rather than
                # erroring.
                continue
            if sid not in input_id_set:
                raise ConsolidationValidationError(
                    f"member entry_id unknown: {sid!r}",
                )
            if sid in seen:
                raise ConsolidationValidationError(
                    f"entry_id appears multiple times: {sid!r}",
                )
            seen.add(sid)
            try:
                member_ids.append(UUID(sid))
            except ValueError as e:
                raise ConsolidationValidationError(
                    f"member entry_id not a UUID: {sid!r}",
                ) from e
        try:
            canonical_uuid = UUID(canonical_raw)
        except ValueError as e:
            raise ConsolidationValidationError(
                f"canonical_entry_id not a UUID: {canonical_raw!r}",
            ) from e
        aliases = [
            str(a).strip()
            for a in canonical_aliases_raw
            if str(a).strip()
        ]
        # Dedupe aliases case-insensitively while preserving order.
        seen_alias: set[str] = set()
        unique_aliases: list[str] = []
        for alias in aliases:
            key = alias.casefold()
            if key in seen_alias:
                continue
            seen_alias.add(key)
            unique_aliases.append(alias)
        groups.append(ConsolidationGroup(
            canonical_entry_id=canonical_uuid,
            canonical_label=canonical_label,
            canonical_aliases=unique_aliases,
            member_entry_ids=member_ids,
        ))

    rejections: list[ConsolidationRejection] = []
    for raw_rej in raw_rejections:
        sid = str(raw_rej.get("entry_id", "")).strip()
        category = str(raw_rej.get("category", "")).strip()
        if not sid or sid not in input_id_set:
            raise ConsolidationValidationError(
                f"rejection entry_id missing or unknown: {sid!r}",
            )
        if sid in seen:
            raise ConsolidationValidationError(
                f"entry_id appears multiple times: {sid!r}",
            )
        if category not in _REJECTION_CATEGORIES:
            raise ConsolidationValidationError(
                f"rejection category not allowed: {category!r}",
            )
        seen.add(sid)
        try:
            rejections.append(ConsolidationRejection(
                entry_id=UUID(sid),
                category=category,
            ))
        except ValueError as e:
            raise ConsolidationValidationError(
                f"rejection entry_id not a UUID: {sid!r}",
            ) from e

    missing = input_id_set - seen
    if missing:
        raise ConsolidationValidationError(
            f"{len(missing)} input entry_id(s) not covered by groups or "
            f"rejections; first missing: {next(iter(missing))!r}",
        )

    return groups, rejections


def _estimate_cost_usd(usage: Any, model: str) -> float:
    """Cost estimate from ``response.usage`` token counts.

    Returns 0.0 when the SDK doesn't surface usage (e.g., a mock in
    tests) or when the model isn't in the small price table below.
    The budget tracker treats 0.0 as "unknown — don't charge"; bumping
    the price table when we add a new model preserves that semantics.
    """
    if usage is None:
        return 0.0
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    if model.startswith("gpt-4o-mini"):
        return (
            (prompt_tokens / 1_000_000) * _GPT_4O_MINI_INPUT_USD_PER_M
            + (completion_tokens / 1_000_000) * _GPT_4O_MINI_OUTPUT_USD_PER_M
        )
    if model.startswith("gpt-4o"):
        return (
            (prompt_tokens / 1_000_000) * _GPT_4O_INPUT_USD_PER_M
            + (completion_tokens / 1_000_000) * _GPT_4O_OUTPUT_USD_PER_M
        )
    logger.debug(
        "consolidate_cost_unknown_model",
        extra={"model": model},
    )
    return 0.0


__all__ = [
    "CatalogConsolidator",
    "CatalogConsolidatorInput",
    "ConsolidationGroup",
    "ConsolidationRejection",
    "ConsolidationResult",
]
