# Livecommerce Test Suite Refactor Plan

Updated: 2026-05-13

This is the working plan for reorganizing the livecommerce product test suite
without weakening coverage during the transition. Treat it as a living document:
each phase should update the "Iteration Log" with new findings, mistakes, and
coverage decisions before moving to the next phase.

## Goals

- Make the default PR gate honest, fast, and representative of supported
  livecommerce behavior.
- Replace hand-maintained backend file allowlists with explicit test lanes.
- Keep feature coverage visible while stale tests are deleted, rewritten, or
  quarantined.
- Separate product-critical tests from old implementation-history tests.
- Make cross-repo contract coverage live in the package that owns the contract.

## Non-Goals

- Do not rewrite product code as part of test reorganization unless a test
  exposes a real product bug.
- Do not make the default PR gate depend on live cloud resources, seeded staging
  data, local agents, real OpenSearch, MinIO, SQS, GPU workers, or Auth0.
- Do not delete a stale test until its intended behavior is either covered
  elsewhere, explicitly unsupported, or tracked in the cleanup ledger.

## Current Baseline

- Backend PR gate: `.github/workflows/test.yml` runs a curated `services/api`
  pytest file allowlist.
- API pytest config: `services/api/pytest.ini` defines only `integration` and
  `quality`; default addopts exclude both.
- Search guardrail: `.github/workflows/search-quality.yml` runs a bounded set of
  search and ingest tests on search-related changes.
- Frontend PR gate: full `services/web` Vitest suite plus `tsc --noEmit`.
- Playwright: `e2e/playwright.config.ts` ignores `premiere-export.spec.ts`
  unless `INCLUDE_LEGACY_E2E=true`.
- Cleanup ledger: `docs/TEST_CLEANUP_LEDGER.md` records quarantined and
  deprecated tests.

Inventory as of 2026-05-13:

- Python service tests excluding virtualenvs: 231 files.
- API test files visible to pytest's API inventory script: 193 files.
- Frontend Vitest files: 99 files.
- Playwright specs: 4 files (`smoke`, `consistency`, `visual-regression`,
  `premiere-export`).
- Current backend workflow allowlist: 60 files.
- Current seeded `core` lane: 97 files, 1533 tests.

## Coverage Invariants

The default CI gate must continue to cover these supported livecommerce
capabilities before any stale tests are removed:

- Auth and tenancy boundaries: org resolution, RBAC, device registration,
  ingest auth, internal auth, production guard behavior.
- Drive sync lifecycle: connection creation/deletion, folder/shared-drive sync,
  metadata propagation, file deletion/reconciliation, S3/proxy metadata.
- Ingest and enrichment: scene ingest, enrichment merge semantics, replay and
  idempotency checks, content type defaults, image/video field shape.
- Search: BM25, semantic, visual fusion, mode routing, Korean normalization,
  pagination/collapse behavior, search analytics.
- Export: proxy-pack initiation, cache/hash behavior, SQS dispatch contract,
  status polling, signed URL response, packaging limits.
- People/faces: cluster listing, rename/delete/merge behavior, thumbnails,
  timeline/video link behavior.
- Shorts/rendering: render idempotency, stale requeue, subtitles, rerender,
  internal router contracts.
- Frontend: TypeScript correctness, current customer-facing flows, search,
  dashboard/videos, people settings, proxy-pack export UI.
- Worker contracts: SQS message adapters, worker callback expectations, API
  payload schemas, shared contract package compatibility.

## Target Test Lanes

Use markers and CI jobs to express why a test runs, not where it happens to
live.

| Lane | Marker/Command | Runs In PR? | Definition |
| --- | --- | --- | --- |
| Core backend | `pytest -m "core"` | Yes | Fast, hermetic product behavior. No docker services or cloud dependencies. |
| Backend unit legacy bridge | current allowlist | Yes until replaced | Existing curated safety net while markers are backfilled. |
| Integration | `pytest -m "integration"` | Scheduled/manual or explicit PR path | Requires local services, Docker Compose, OpenSearch, SQS, MinIO, DB, or service containers. |
| Quality | `pytest -m "quality"` | Search-related path guard and scheduled | Search relevance/eval tests requiring fixtures or seeded data. |
| External | `pytest -m "external"` | Manual only | Touches real cloud, staging, Auth0, S3, AWS, or non-hermetic APIs. |
| Slow | `pytest -m "slow"` | Scheduled/manual | Expensive but valid tests; can combine with other markers. |
| Legacy | `pytest -m "legacy"` | No default | Retained temporarily for old flows or rollback context. Must have ledger entry. |
| Deprecated | `pytest -m "deprecated"` | No default | Historical tests awaiting deletion or rewrite. Must have ledger entry. |
| Frontend unit | `npx vitest run` | Yes | Current full Vitest suite. |
| TypeScript | `npx tsc --noEmit` | Yes | Current full TS type check. |
| E2E smoke | `playwright test smoke.spec.ts consistency.spec.ts` | Scheduled/manual first | Browser smoke against local or staging. |
| Visual regression | `playwright test visual-regression.spec.ts` | Manual/scheduled | Screenshot drift; not a blocking PR gate until baselines are stable. |

## Refactor Phases

### Phase 0: Freeze The Baseline

Status: complete for the current baseline.

Actions:

- Keep the existing backend allowlist in `.github/workflows/test.yml` unchanged
  until marker coverage is proven equivalent.
- Keep `docs/TEST_CLEANUP_LEDGER.md` as the source of truth for quarantines.
- Record current test counts and commands in this plan.
- Any newly ignored, skipped, or deleted test must get a ledger entry first.
- Add a small test inventory script or documented command that excludes
  `.venv`, `node_modules`, `.next`, Playwright artifacts, and generated output.

Exit criteria:

- Existing CI still passes.
- No test is removed without ledger coverage.
- Inventory commands are repeatable and do not include dependency tests.

### Phase 1: Marker Taxonomy And Pytest Plumbing

Status: complete.

Actions:

- Extend `services/api/pytest.ini` with markers:
  `core`, `external`, `slow`, `legacy`, `deprecated`, and optionally
  `contract`.
- Keep the default addopts as `-m "not integration and not quality"` during the
  first marker pass to avoid surprising local behavior.
- Add a non-blocking CI/report command that lists unmarked API tests:
  `pytest --collect-only -q` plus a small parser, or a simple `rg`-based report
  if collection is blocked by dependencies.
- Add comments in `.github/workflows/test.yml` explaining the migration path:
  allowlist remains the blocking gate until `core` coverage reaches parity.
- Seed `tests/core_test_files.txt` from the real workflow allowlist and use
  `tests/conftest.py` to apply `pytest.mark.core` during collection.
- Add `.github/workflows/test.yml` shadow reporting: inventory plus non-blocking
  `pytest -m core --tb=short`.

Exit criteria:

- All markers are registered; no unknown-marker warnings.
- Marker addition does not change which tests run in PRs.
- Local seed command passes:
  `.venv/bin/pytest -m core --tb=short -q`.

### Phase 2: Classify Product-Critical API Tests

Status: in progress.

Actions:

- Classify the current backend allowlist first as `core`.
- For each unallowlisted API test file, assign one of:
  `core`, `integration`, `quality`, `external`, `slow`, `legacy`, or
  `deprecated`.
- Work feature area by feature area, not alphabetically:
  auth/tenancy, ingest/enrichment, search, drive sync, export, people, shorts,
  worker contracts.
- Run each newly classified `core` group locally before adding it to the PR
  gate.
- If a file fails because of missing sibling packages, decide whether to:
  checkout/install the sibling in CI, move the test to the owning repo, or mark
  it integration/contract until packaging is fixed.
- Current remaining unclassified API test files: 87.

Exit criteria:

- Every API test file has an explicit lane decision.
- Any non-core decision has a reason in the ledger or a feature-area audit note.
- The core lane includes at least the behavior currently covered by the
  allowlist.

### Phase 3: Replace The Backend Allowlist

Actions:

- Add a new CI backend job that runs `pytest -m "core" --tb=short`.
- Run the old allowlist job and new marker job side by side for at least one PR.
- Compare collected test counts and feature-area coverage.
- Once equivalent or stronger, remove the file allowlist and keep marker-based
  core as the blocking backend PR gate.

Exit criteria:

- Marker-based core passes in CI.
- It covers all files previously in the allowlist or an intentional replacement
  is documented.
- CI comments no longer overclaim coverage.

### Phase 4: Repair Or Delete Quarantined Tests

Actions:

- Process `docs/TEST_CLEANUP_LEDGER.md` one row at a time.
- For each row, choose exactly one outcome:
  `restore into current lane`, `rewrite current behavior`, or `delete`.
- Current known decisions:
  - Legacy Premiere/FCPXML E2E: rewrite as proxy-pack E2E.
  - Media-pipelines Phase 3 scene helper tests: keep quarantined unless
    transcode-piggyback scene splitting is revived.
  - Worker SDK RabbitMQ test: keep only if on-prem RabbitMQ remains supported.
- When deleting, state which current test now covers the behavior or why the
  behavior is unsupported.

Exit criteria:

- Ledger has no vague follow-ups.
- Deprecated tests have deletion dates or owner decisions.

### Phase 5: Add Current E2E Smoke Coverage

Actions:

- Replace `premiere-export.spec.ts` as the export representative with a
  proxy-pack E2E:
  login/dev auth -> search or browse -> add scenes to basket -> initiate
  proxy-pack -> poll job -> verify downloadable URL/status.
- Keep the old Premiere spec behind `INCLUDE_LEGACY_E2E=true` until the
  proxy-pack E2E is stable.
- Decide whether E2E runs against local dev, staging, or both. If staging, mark
  it external and avoid blocking normal PRs initially.

Exit criteria:

- Current customer export path has E2E coverage.
- Legacy FCPXML E2E can be deleted or permanently manual-only.

### Phase 6: Cross-Repo Contract Relocation

Actions:

- Identify tests in SaaS that primarily assert:
  shared schemas, SQS message shapes, worker SDK adapters, media pipeline scene
  contracts, or package import surfaces.
- Move or duplicate the durable assertion into the owning repo:
  `heimdex-media-contracts`, `heimdex-worker-sdk`, or
  `heimdex-media-pipelines`.
- Keep SaaS tests only for SaaS behavior: routes, auth, persistence, dispatch,
  and response shape.

Exit criteria:

- CI no longer relies on hidden sibling-package assumptions for core tests.
- Contract changes fail in the package that owns the contract.

### Phase 7: Scheduled And Manual Lanes

Actions:

- Add scheduled/manual workflows for:
  integration tests, quality tests, external staging smoke, visual regression,
  and slow worker tests.
- Keep these lanes honest about prerequisites in workflow names and comments.
- Store failures as artifacts where useful, especially Playwright traces and
  search quality summaries.

Exit criteria:

- Expensive or environment-dependent tests are visible without blocking every
  PR.
- Failures identify the broken feature area and required environment.

## Coverage Gap Controls

Before deleting or downgrading any test:

1. Identify the supported behavior it was meant to protect.
2. Find the current replacement test, or create one.
3. Confirm the replacement is in the correct lane.
4. Update `docs/TEST_CLEANUP_LEDGER.md`.
5. Run the affected lane locally.
6. If the test exposed obsolete behavior, document why it is unsupported.

Before changing CI:

1. Run the old and new commands locally where feasible.
2. Compare collected test counts and skipped/error counts.
3. Keep old and new jobs side by side for at least one transition PR.
4. Do not remove the old gate until the new gate is equal or stronger.

## Useful Commands

Inventory service Python tests:

```bash
rg --files -g 'test_*.py' -g '!**/.venv/**' services | sort
```

Count service Python tests:

```bash
rg --files -g 'test_*.py' -g '!**/.venv/**' services | wc -l
```

Count tests by service:

```bash
rg --files -g 'test_*.py' -g '!**/.venv/**' services \
  | sed 's#/tests/.*##' \
  | sort \
  | uniq -c
```

Inventory frontend unit tests:

```bash
rg --files -g '*.test.ts' -g '*.test.tsx' -g '!**/node_modules/**' services/web
```

Inventory Playwright specs:

```bash
rg --files -g '*.spec.ts' -g '!**/node_modules/**' e2e
```

Find skip/quarantine candidates:

```bash
rg -n "skip|skipif|xfail|importorskip|pytestmark|legacy|deprecated" \
  services e2e docs .github \
  -g '!**/.venv/**' \
  -g '!**/node_modules/**' \
  -g '!**/.next/**'
```

## Iteration Log

### 2026-05-13

- Added `docs/TEST_CLEANUP_LEDGER.md` to track quarantined and deprecated test
  suites.
- Quarantined legacy Playwright Premiere export spec behind
  `INCLUDE_LEGACY_E2E=true`.
- Quarantined stale media-pipelines scene helper tests in that repo's
  `pyproject.toml`, including `test_split_scenes_cached.py`.
- Removed untracked media-pipelines Phase 3 scene-splitting leftovers after
  confirming they were not current product code.
- Mistake found during inventory: a broad `find services ...` command walked
  into `services/api/.venv` and listed third-party package tests. Future
  inventory commands must exclude `.venv` and should prefer `rg --files`.
- Added API marker taxonomy in `services/api/pytest.ini`: `core`, `contract`,
  `external`, `slow`, `legacy`, and `deprecated`.
- Added `services/api/scripts/test_inventory.py` as a stdlib-only report for
  API test files, workflow allowlist coverage, lane markers, and unmarked files.
- Seeded `services/api/tests/core_test_files.txt` from the active backend
  workflow allowlist and applied `pytest.mark.core` from that manifest in
  `tests/conftest.py`.
- Mistake found during core seeding: the first workflow parser counted test
  paths inside comments, including seven `shorts_auto` files that the workflow
  explicitly excludes. Fixed the parser to ignore commented lines and corrected
  the core manifest from 67 files to 60 files.
- Collection blocker found: `pytest -m core` still imports unselected modules
  before marker deselection. `tests/test_drive_transcode.py` imported
  `heimdex_media_pipelines` directly and broke collection when the sibling
  package was absent. Reclassified it as a `contract` test with
  `pytest.importorskip`.
- CI-risk blocker found: three `shorts_auto` tests imported
  `heimdex_media_contracts.shorts.scorer` directly even though the workflow
  comments say that package surface may be unavailable in CI. Reclassified
  those direct-import files as `contract` tests with `pytest.importorskip`.
- Test bug found while running the seeded core lane: two
  `test_post_render_hook.py` assertions expected structlog output in
  stdout/stderr, but pytest captured it through logging. Updated them to assert
  against `caplog`.
- Current cleaned inventory: 231 service Python test files excluding virtualenvs,
  193 API test files in the API inventory, 99 frontend Vitest files, and 4
  Playwright specs.
- Current API lane report: 60 workflow allowlist files, 60 seeded `core` files,
  4 `contract` files, 5 `integration` files, 1 `quality` file, and 124
  unclassified API files.
- Verification: `.venv/bin/pytest -m core --tb=short -q` passes with
  957 passed, 1 skipped, 1990 deselected, and 2 warnings.
- Promoted the first Phase 2 feature slice into `core`: auth/tenancy and
  ingest/enrichment. Added 15 hermetic API files to `tests/core_test_files.txt`:
  `test_auth_security.py`, `test_device_heartbeat.py`,
  `test_device_pairing.py`, `test_device_registration.py`,
  `test_ingest_auth.py`, `test_ingest_rate_limit.py`,
  `test_ingest_replay.py`, `test_internal_auth_helper.py`,
  `test_internal_enrich.py`, `test_internal_ingest.py`, `test_oidc.py`,
  `test_org_hardening.py`, `test_rbac.py`, `test_tenancy.py`, and
  `test_user_model.py`.
- Repaired stale enrichment tests after discovering that current
  `SceneIngestService.enrich_scenes()` now performs a user-override protection
  lookup through `SceneOverrideRepository.get_overridden_fields()`. Tests now
  mock that DB lookup explicitly.
- Repaired one stale internal enrich endpoint test after the route moved from
  legacy `_token` dependency injection to `verified_service_id` from
  `verify_service_identity`.
- Repaired two OIDC tests to assert the current generic OIDC/Auth0 validation
  messages and set `oidc_issuer=""` so the domain/audience configuration guard
  is exercised before token-header parsing.
- Updated `services/api/scripts/test_inventory.py` wording so core-manifest
  growth beyond the workflow allowlist is reported as progress instead of a
  generic mismatch.
- Verification after promotion:
  `.venv/bin/pytest -m core --tb=short -q` passes with 1170 passed, 1 skipped,
  1777 deselected, and 2 warnings.
- Current API lane report: 60 workflow allowlist files, 75 seeded `core` files,
  4 `contract` files, 5 `integration` files, 1 `quality` file, and 109
  unclassified API files.
- Promoted the second Phase 2 feature slice into `core`: drive sync and
  internal drive routing. Added 13 hermetic API files to
  `tests/core_test_files.txt`: `test_drive_config.py`,
  `test_drive_folder_connection_router.py`, `test_drive_oauth_scope.py`,
  `test_drive_rbac.py`, `test_drive_s3.py`, `test_drive_scene_pipeline.py`,
  `test_drive_schemas.py`, `test_drive_sync.py`,
  `test_drive_worker_discover_incremental.py`,
  `test_internal_drive_processing_router.py`, `test_internal_drive_router.py`,
  `test_internal_drive_sync_router.py`, and `test_watched_folder_router.py`.
- Repaired stale drive router tests after current endpoints required the admin
  dependency from `require_role(UserRole.ADMIN)`. Test apps now override
  `get_current_user` with an admin-shaped user.
- Repaired the folder connection direct-call test after
  `create_folder_connection()` gained explicit `_admin` and `secret_repo`
  dependencies.
- Repaired an internal drive router mock after current STT completion logic
  reads `drive_file.scene_count`; the test helper now supplies a concrete
  integer instead of a `MagicMock`.
- Drive-worker artifact upload tests in `test_drive_enrichment.py` were not
  promoted. They import drive-worker code and currently fail against current
  worker behavior because expected `enrichment_state` output is stale. Treat as
  a cross-service worker test to repair or relocate, not API core.
- Verification after drive promotion:
  `.venv/bin/pytest -m core --tb=short -q` passes with 1428 passed, 1 skipped,
  1519 deselected, and 2 warnings.
- Current API lane report: 60 workflow allowlist files, 88 seeded `core` files,
  4 `contract` files, 5 `integration` files, 1 `quality` file, and 96
  unclassified API files.
- Drafted and executed the third Phase 2 feature slice: people/faces. Candidate
  files were `test_face_thumbnail_s3.py`, `test_people_bulk_delete.py`,
  `test_people_last_seen.py`, `test_people_merge.py`, `test_people_search.py`,
  `test_people_similar.py`, `test_people_timeline.py`,
  `test_people_video_link.py`, and `test_video_people.py`.
- The people/faces slice passed hermetically without repairs:
  `.venv/bin/pytest <people/faces slice> --tb=short -q` passed with
  105 tests.
- Promoted all nine people/faces candidate files into `core`.
- Verification after people/faces promotion:
  `.venv/bin/pytest -m core --tb=short -q` passes with 1533 passed, 1 skipped,
  1414 deselected, and 2 warnings.
- Current API lane report: 60 workflow allowlist files, 97 seeded `core` files,
  4 `contract` files, 5 `integration` files, 1 `quality` file, and 87
  unclassified API files.
