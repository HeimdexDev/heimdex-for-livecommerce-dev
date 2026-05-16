// ============================================================================
// Single-render adapter for EditClipsPage.
//
// EditClipsPage was authored against the wizard's multi-clip flow and
// consumes a ``ScanOrderStatusResponse`` (one parent + N children) via
// ``useScanOrder``. The saved-shorts edit surface
// (``/export/shorts/[renderJobId]/edit``) has a single render job, no
// scan-order parent. Rather than refactor EditClipsPage to fork on the
// two shapes everywhere, this hook fabricates the
// ``ScanOrderStatusResponse`` shape from a single render so the page
// can be reused unchanged.
//
// What this hook does:
//   1. Fetches ``getRenderJob(renderJobId)`` exactly once.
//   2. Builds a synthetic ``ScanOrderStatusResponse`` where:
//      - ``parent.stage = "committed"`` (terminal-success) — the
//        only consumer is the redirect-on-terminal logic in
//        ``WizardStepResult``, which we never route through here.
//        ``EditClipsPage`` itself doesn't gate on parent stage, so the
//        value is benign.
//      - ``children`` is a single-element array carrying the render
//        as a ``render_child`` job. Fields the editor reads
//        (``render_job_id``, ``shorts_index``, ``stage``,
//        ``render_status``, ``completed_at``) are mapped 1:1 from
//        the render. Everything else is filled with sensible defaults.
//
// What it does NOT do:
//   - Poll for updates. EditClipsPage already polls per-clip via
//     ``getShortComposition`` + ``getRenderJob`` (the lazy clip-load
//     effect); a parallel scan-order poll would be redundant.
//   - Carry effective_render_job_id forward. The new route is
//     responsible for resolving the leaf BEFORE mounting EditClipsPage
//     — by the time we're in single-render mode, the renderJobId is
//     already the leaf.
//
// Contract: the returned object must satisfy ``UseScanOrderResult``
// (the same shape ``useScanOrder`` returns). If ``useScanOrder``
// grows fields, this hook mirrors them — drift is caught at compile
// time via the explicit return type annotation.
// ============================================================================

import { useEffect, useMemo, useState } from "react";

import { getRenderJob } from "@/lib/api/shorts-render";
import type { RenderJobResponse } from "@/lib/api/highlight-reel";
import type {
  JobStatusResponse,
  ScanOrderStatusResponse,
  ScanStage,
} from "@/lib/types/shorts-auto-product-wizard";

import type { UseScanOrderResult } from "./useScanOrder";

type TokenGetter = () => Promise<string | null>;

function mapRenderStatusToScanStage(status: string): ScanStage {
  // Render-side status (queued/rendering/completed/failed) → wizard
  // scan-stage (queued/rendering/done/failed). The wizard stage is
  // what EditClipsPage's sibling components read for "is this clip
  // ready to play" checks.
  switch (status) {
    case "completed":
      return "done";
    case "failed":
      return "failed";
    case "rendering":
      return "rendering";
    default:
      return "queued";
  }
}

function renderToJobStatus(render: RenderJobResponse): JobStatusResponse {
  const stage = mapRenderStatusToScanStage(render.status);
  return {
    job_id: render.id,
    kind: "render_child",
    stage,
    progress_pct: stage === "done" ? 100 : 0,
    progress_label: null,
    completed_at: render.completed_at,
    failed_at: null,
    cancelled_at: null,
    error_code: null,
    error_message: render.error,
    render_job_id: render.id,
    render_status: render.status,
    parent_job_id: null,
    shorts_index: 1,
    cost_usd_estimate: "0.00",
  };
}

function buildSyntheticStatus(
  render: RenderJobResponse,
): ScanOrderStatusResponse {
  const child = renderToJobStatus(render);
  const isComplete = child.stage === "done";
  const isFailed = child.stage === "failed";
  return {
    parent: {
      job_id: render.id, // re-use; this field is never the editor's primary key
      kind: "scan_order",
      stage: "committed", // terminal-success; matches "wizard finished" expectation
      progress_pct: 100,
      progress_label: null,
      completed_at: render.completed_at,
      failed_at: null,
      cancelled_at: null,
      error_code: null,
      error_message: null,
      render_job_id: null,
      render_status: null,
      parent_job_id: null,
      shorts_index: null,
      cost_usd_estimate: "0.00",
    },
    children: [child],
    children_complete: isComplete ? 1 : 0,
    children_failed: isFailed ? 1 : 0,
    children_total: 1,
  };
}

export function useSyntheticScanOrder(
  renderJobId: string | null,
  tokenGetter: TokenGetter,
): UseScanOrderResult {
  const [render, setRender] = useState<RenderJobResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!renderJobId) {
      setRender(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setError(null);
    (async () => {
      try {
        const fetched = await getRenderJob(renderJobId, tokenGetter);
        if (!cancelled) setRender(fetched);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [renderJobId, tokenGetter]);

  const status = useMemo<ScanOrderStatusResponse | null>(
    () => (render ? buildSyntheticStatus(render) : null),
    [render],
  );

  // ``cancel`` is part of the UseScanOrderResult contract; in single-
  // render mode there's nothing to cancel (no polling). Return a
  // resolved no-op so callers can `await cancel()` uniformly.
  const cancel = useMemo(() => async () => {}, []);

  return {
    status,
    error,
    isPolling: render === null && error === null && renderJobId !== null,
    cancel,
  };
}
