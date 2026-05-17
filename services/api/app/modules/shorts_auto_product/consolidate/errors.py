"""Typed errors for the post-enumeration catalog consolidation pipeline.

The orchestrator branches on three failure shapes:

* :class:`ConsolidationLLMError` — the gpt-4o call timed out, returned
  malformed JSON, or hit a content / rate limit. The orchestrator logs
  at warning and short-circuits to zero rows touched; raw catalog
  stays visible.

* :class:`ConsolidationValidationError` — the LLM response parsed but
  failed semantic validation (entry_id hallucination, duplicate
  membership across groups, empty canonical label). Defense against a
  schema-conformant-but-wrong payload poisoning the catalog. Same
  short-circuit semantics as the LLM error.

* :class:`ConsolidationError` (base) — anything else.

Distinct from :mod:`shorts_auto_product.enumerate_stt.errors`. Same
naming convention but a different lifecycle: consolidate runs AFTER
both vision and STT enumeration land their rows.
"""

from __future__ import annotations


class ConsolidationError(Exception):
    """Base for catalog consolidation failures the orchestrator handles."""


class ConsolidationLLMError(ConsolidationError):
    """The consolidate LLM call failed — timeout, schema mismatch,
    OpenAI rate limit, content filter.

    The orchestrator catches this and short-circuits: no rows are
    rejected, no canonical labels are updated, and the raw catalog
    remains visible. Repeated failures across multiple scans should
    page on the existing OpenAI cost / error rate dashboard.
    """


class ConsolidationValidationError(ConsolidationError):
    """The LLM response parsed as JSON but failed semantic validation.

    Examples: an ``entry_id`` not present in the input set
    (hallucination), the same ``entry_id`` appearing in two groups,
    an empty ``canonical_label`` after strip, ``member_entry_ids``
    that includes the canonical's own id without that being explicit.

    Same short-circuit semantics as the LLM error — we'd rather show
    the raw catalog than apply a wrong merge.
    """
