"""Post-enumeration catalog consolidation (merge + non-sellable filter).

Sits AFTER the parallel vision + STT enumeration paths land their rows.
One gpt-4o call inspects the union of catalog rows for a video and
emits two simultaneous decisions:

* **Merge.** Rows referring to the same physical product collapse
  into one canonical row. Korean / branded labels win over English /
  generic forms. The merged row's ``llm_label`` and
  ``spoken_aliases`` are updated in place; absorbed rows are
  soft-rejected with ``rejected_reason='duplicate_of:<canonical_uuid>'``.

* **Reject non-sellable.** Host equipment, ambient props, on-screen
  graphics, bare generic English nouns ("Bottle", "Box"), and
  placeholder labels ("Product 1") are soft-rejected with
  ``rejected_reason='non_sellable:<category>'``.

No schema change: reuses existing ``rejected_at`` / ``rejected_reason``
columns. The existing ``list_active_by_video`` filter
(``rejected_at IS NULL``) hides absorbed and non-sellable rows from
the gallery automatically.

Triggered fire-and-forget from the vision worker's ``/complete``
callback after a configurable grace sleep (default 105s) that gives
STT enumeration a chance to finish first. Failures never break the
wizard — the raw catalog stays visible.

Loose-coupling: imports ONLY from ``openai``, :mod:`app.config`,
:mod:`app.db.base`, :mod:`app.modules.shorts_auto_product.models`, the
catalog repository, and own-module symbols. NO cross-imports from
other ``app.modules.*``.
"""
