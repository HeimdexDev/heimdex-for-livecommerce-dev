"""Transcript-driven product enumeration (STT-first path).

Complements the vision keyframe enumerator (``product-enumerate-worker``).
Runs INLINE in the API process — no GPU, no SQS, no worker. Discovers
products purely from what the host says, covering two video classes
the vision path misses:

* **Banner-heavy intros** that bias the keyframe sampler toward
  graphic overlays (e.g., ``gd_907a1b5c8cdf5bb5`` — supplements behind
  60% 할인 banners).
* **No-clear-visuals verticals** like travel commerce — destinations,
  tours, subscription tiers that aren't physical objects in frame.

End-to-end: :func:`service.run_stt_enumeration` is fire-and-forget'd
from ``shorts_auto_product/service.py::enqueue_scan`` alongside the
existing SQS publish to the vision worker. The two paths run in
parallel and the wizard polls the merged catalog.

Plan: ``.claude/plans/shorts-auto-product-stt-enum-2026-05-06.md``.
Loose-coupling: this module imports ONLY from ``app.config``,
``opensearchpy``, ``openai``, ``heimdex_media_contracts.product``, and
own-module symbols. NO cross-imports from other ``app.modules.*``.
"""
