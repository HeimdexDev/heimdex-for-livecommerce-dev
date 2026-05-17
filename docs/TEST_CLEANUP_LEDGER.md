# Test Cleanup Ledger

Updated: 2026-05-13

This ledger tracks test suites that are intentionally kept out of the default
signal path while the livecommerce product test surface is cleaned up.

Refactor sequencing and safety rules live in `docs/TEST_SUITE_REFACTOR_PLAN.md`.

## Active Default Coverage

- Backend PR gate: `.github/workflows/test.yml` backend allowlist.
- Frontend PR gate: full `services/web` Vitest suite plus `tsc --noEmit`.
- Search guardrail: `.github/workflows/search-quality.yml` for search/ingest
  changes.

## Deprecated Or Quarantined

| Scope | Status | Reason | Follow-up |
| --- | --- | --- | --- |
| `e2e/premiere-export.spec.ts` | ignored by Playwright config unless `INCLUDE_LEGACY_E2E=true` | Targets legacy Auth0/manual FCPXML flow. The customer-facing export path now defaults to proxy-pack, and the FCPXML tab is hidden in `ExportModal`. This spec is also gitignored, so the tracked quarantine lives in `e2e/playwright.config.ts`. | Replace with proxy-pack E2E that covers basket -> initiate job -> poll -> download URL. |
| `heimdex-media-pipelines/tests/scenes/test_boundaries_from_cuts.py` | ignored by `heimdex-media-pipelines` pytest config | Imports `boundaries_from_cuts`, which is not present in current `scenes.detector`. | Either restore a current pure helper and update tests, or delete after confirming no current caller needs it. |
| `heimdex-media-pipelines/tests/scenes/test_extract_scene_cuts_ms.py` | ignored by `heimdex-media-pipelines` pytest config | Imports `extract_scene_cuts_ms`/`probe_duration_ms`, while current detector exposes private `_probe_duration_ms` and inline cut extraction. | Decide whether to promote helpers or remove stale tests. |
| `heimdex-media-pipelines/tests/scenes/test_scene_pipeline.py` | ignored by `heimdex-media-pipelines` pytest config | Depends on the same missing promoted detector helpers through `scene_pipeline.py`. | Repair alongside scene helper decision. |
| `heimdex-media-pipelines/tests/scenes/test_split_scenes_cached.py` | ignored by `heimdex-media-pipelines` pytest config | Exercises an unfinished `split_scenes(..., cached_visual_cuts_ms=..., total_duration_ms=...)` API that is not present in current `scenes.splitter`. | Repair only if the transcode-piggyback scene splitting work is revived. |
| `heimdex-worker-sdk/tests/test_rabbitmq_client.py` | optional import skip when `pika` is absent | RabbitMQ is an optional on-prem backend; cloud livecommerce uses SQS/Aircloud. | Keep only if on-prem remains supported; otherwise remove RabbitMQ client and tests together. |

## Next Cleanup Targets

- Replace the backend allowlist with marker-based lanes: `core`, `feature_flagged`,
  `integration`, and `quality`.
- Move any useful assertions from deprecated `services/worker` face/speech tests
  into `heimdex-media-contracts` or `heimdex-media-pipelines`; then remove the
  dead `face-worker` test directory.
- Backfill marker-based API classification so the backend allowlist can shrink
  into policy instead of remaining a long hand-maintained file list.
