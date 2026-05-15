"""Vendored pure-math subset of ``heimdex_media_pipelines.product_track``.

Source: ``heimdex-media-pipelines`` v0.12.3 (commit ``5d82c7d``).
Vendored 2026-05-03 for the wizard child runner (Phase 4 PR #6) so the
API can score windows + select subsets + build stitch plans without
growing an install-time dependency on the pipelines repo.

## Why vendored, not pip-installed

* ``heimdex-media-pipelines`` is not on PyPI — its ``release.yml``
  builds wheels and attaches them to GitHub Releases but does NOT
  run ``pypa/gh-action-pypi-publish``. Workers install it via Docker
  ``COPY ../heimdex-media-pipelines/ /tmp/...`` from a workspace-root
  build context. The API uses a service-scoped Docker context, so
  adopting the same install model would mean build-context surgery
  across compose, GHA, and deploy scripts.
* Plan §15 loose-coupling: "API never imports
  ``heimdex_media_pipelines``." Vendoring honors this literally —
  the runner imports ``app.lib.product_track`` and the upstream
  package stays out of the API venv entirely.
* The five files vendored here are pure-math (no transformers, no
  opencv, no numpy beyond stdlib-equivalent uses), ~600 LOC total,
  stable for the past 4 weeks (v0.10 → v0.12.3 only touched the
  composition / blur subsystems, not ``product_track``). The
  GPU-using siblings (``siglip2_retrieval``, ``sam2_pass``,
  ``sam2_loader``, ``pipeline``) stay in the pipelines repo where
  the workers run them.

Note: torch is already a top-level API dep (via ``sentence-transformers``
for cross-encoder reranking), so "torch-free" is not the win here.
The win is no first-PyPI-publish risk and no Docker-context surgery.

## Sync ritual

When the upstream pure-math files change (rare — track via
``git log heimdex-media-pipelines/src/heimdex_media_pipelines/product_track/``):

1. Diff the upstream file against the vendored copy:
   ``diff -u heimdex-media-pipelines/src/heimdex_media_pipelines/product_track/<file>.py services/api/app/lib/product_track/<file>.py``
2. Apply the upstream changes by hand. The only mechanical rewrite
   is ``heimdex_media_pipelines.product_track`` →
   ``app.lib.product_track`` in cross-module imports.
3. Bump the source-of-truth comment at the top of each vendored
   file to reference the new upstream commit.
4. Run ``pytest tests/lib/product_track/`` — the smoke test
   imports the chain and asserts ``heimdex_media_pipelines`` is
   NOT importable in the API venv (the actual coupling we prevent).

## What's NOT vendored

* ``siglip2_retrieval`` — calls SigLIP2 via transformers
* ``sam2_pass`` / ``sam2_loader`` — calls SAM2 via transformers
* ``pipeline`` — orchestrator that wires the GPU pieces together;
  callers of the orchestrator are workers, not the API.

## Modules

* :mod:`config` — ``TrackingConfig`` dataclass + threshold defaults
* :mod:`window_assembly` — ``AssembledWindow`` types
* :mod:`alignment` — ``AnnotatedWindow`` + alignment helpers
* :mod:`subset_selector` — ``ScoredWindow``, ``score_windows``,
  ``select_subset``, ``GreedyPicker``, ``SubsetPicker`` Protocol
* :mod:`stitching` — ``StitchPlan`` + ``build_stitch_plan``
"""
