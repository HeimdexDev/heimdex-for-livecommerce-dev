# Blur v0.10 — Follow-Ups

Non-blocking improvements identified during the Phase 1–5 review. None
of these gate the v0.10 rollout; they are parked here so later sessions
can pick them up without a full feature re-audit.

## Backend / API

### 1. Export panel orphan tracking
**Symptom**: if the user navigates away mid-export, the `exportId` only
lives in React state. There is no way to resume tracking the export
without a dedicated list endpoint.

**Owner surface**: `services/api/app/modules/blur/router.py`,
`services/web/src/features/blur/components/BlurDetailPage.tsx`

**Fix sketch**: add `GET /api/blur/jobs/{job_id}/exports` (org-scoped,
paginated). Frontend renders a small "recent exports" strip in
`BlurExportPanel` that polls if any are active. ~1/2 day.

**Why not now**: the primary export flow works within a single
page load; orphan recovery is a UX nicety, not a correctness issue.

---

### 2. Manifest JSON shape validation on the frontend
**Symptom**: if S3 returns a corrupt or truncated `manifest.json`,
`BlurTimeline` silently renders blank. The user sees "0 detections"
with no error.

**Owner surface**: `services/web/src/features/blur/components/BlurDetailPage.tsx`
(`useBlurManifest` hook).

**Fix sketch**: add a lightweight runtime shape check
(`zod` or a hand-rolled guard) before handing the JSON to
`BlurTimeline`. On failure, show an error toast with a retry button.
~1 hour.

**Why not now**: we write the manifest ourselves — the risk is
network-layer only, and the blank-timeline fallback is not dangerous.

---

### 3. Timeline bucketing for long videos
**Symptom**: a 30-minute video with ~10k detections renders 10k SVG
`<rect>` nodes in `BlurTimeline`. Likely a 200+ ms layout pass on
mid-range laptops.

**Owner surface**: `services/web/src/features/blur/components/BlurDetailPage.tsx`
(`BlurTimeline`).

**Fix sketch**: bucket detections by `t_ms` into
`Math.max(1, totalMs / 800)` bins per lane and render one rect per
non-empty bucket. On hover, expand the bucket contents in a tooltip.
~2 hours.

**Why not now**: unknown if it matters on real traffic. Defer until
Phase 7's perf pass measures it.

---

### 4. Worker concurrency for parallel blur + export
**Symptom**: `drive-blur-worker` runs with `drive_blur_concurrency=1`.
A customer-requested export while a blur job is running on the same
GPU box will queue behind it (correct, but slow). Exports are
CPU-bound and could run in a second slot without fighting OWLv2 for
GPU.

**Owner surface**: `services/drive-blur-worker/src/worker.py`,
`services/drive-blur-worker/src/dispatcher.py`

**Fix sketch**: bump `drive_blur_concurrency=2`, verify the semaphore
path is thread-safe across a blur-job and an export running
concurrently. Add integration test that exercises both in parallel.
Note: pipeline warm singleton config mutation is NOT safe under
concurrency >1 today; either make it per-call or add a lock.
~1 day including safety work.

**Why not now**: export throughput is not a v1 bottleneck; exports
are infrequent during testing.

---

### 5. Per-run blur job history on the detail page
**Symptom**: `BlurDetailPage` reads `items[0]` from the list endpoint
(most recent). If the user re-runs blur with different options, only
the latest run is visible; older runs become invisible even though
their S3 artifacts still exist.

**Owner surface**: `services/web/src/features/blur/components/BlurDetailPage.tsx`

**Fix sketch**: add a "job history" dropdown in `BlurHeader` listing
every `BlurJob` for the video, defaulting to the latest. Matches the
plan's "no re-run with different settings" v1 scope, so this is
strictly optional.

**Why not now**: plan §3 answer #3 explicitly said re-runs aren't a v1
thing — "run once with everything on, toggle off at export".

---

## Cross-cutting

### 6. Share link that respects blur toggle state
**Symptom**: share links are explicitly out of scope for v1 (plan §11
answer #2). When the share subsystem eventually lands, it must thread
blur state through the URL so a shared link opens in the same
blurred/unblurred/category state the sender saw.

**Owner surface**: wherever share links are generated (not yet built).

**Fix sketch**: extend the share URL with
`?blur=on|off&layers=face,logo` query params; `BlurDetailPage` reads
them on mount and restores UI state accordingly.

**Why not now**: share link subsystem does not exist yet.

---

### 7. Credit-based quota
**Symptom**: every blur run and every export currently consumes GPU
time for free. When the feature exits testing, the per-org credit
model from the plan needs to land.

**Owner surface**: `services/api/app/modules/blur/service.py`,
`services/api/app/modules/blur/export_service.py`,
`services/api/app/config.py`.

**Fix sketch**: add a `blur_credits` column on `orgs`, decrement on
job create, reject with 402 when exhausted, daily reset cron.
Customer-facing balance display on the detail page header.

**Why not now**: plan §11 answer #2 said "do not implement the credit
model yet — we are still in the testing phase".

---

## Operations / Rollout gates (tracked here for visibility)

These are NOT follow-ups — they are hard prerequisites for flipping
`BLUR_EXPORT_ENABLED=true` on staging / prod. Documented here so a
later session has a single place to check.

1. **Publish `heimdex-media-contracts` v0.10.0 to PyPI** (dev works
   via volume mount; staging/prod workers pin from PyPI).
2. **Run migration 048** on staging DB, then prod.
3. **Verify ffmpeg encoders** in `drive-blur-worker` image include
   both `ffv1` and `prores_ks` (handled in Phase 6 Dockerfile check).
4. **Apply S3 lifecycle rules** for `blurred/*/masks/*` (180d) and
   `blur_exports/*` (7d) (written in Phase 6, applied by operators).
5. **Manual NLE import test**: open an exported ProRes 4444 `.mov`
   in DaVinci Resolve AND Premiere Pro, verify alpha channel
   interprets correctly and composites over the original.
6. **Browser E2E test** of the full blur detail page flow, including
   timeline rendering, player toggle, export submission, and
   download. Lands in Phase 7.
