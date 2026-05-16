// ============================================================================
// Refined render chain hook (PR 5 of whisper-subtitles plan).
//
// Given an initial render job id, follow the
// ``replaced_by_render_job_id`` pointer to its refined child (if any)
// and expose whichever job is currently canonical.
//
// Lifecycle (silent swap; the operator's view updates without an
// explicit "refined" badge — see plan §0 leans):
//
//   1. Poll the initial job. While not completed, keep polling.
//   2. Initial completes:
//      - replaced_by is null → may still appear later. Wait up to
//        REFINEMENT_GRACE_MS for it. If none appears, settle on the
//        initial render (canonical).
//      - replaced_by is set → switch target to the child, keep
//        polling. When the child completes, settle on the child.
//   3. Initial fails → settle on the failure (no refinement attempt).
//
// Total wait is bounded:
//   - Up to REFINEMENT_GRACE_MS (30s) for replaced_by to appear after
//     the parent completes.
//   - Up to CHILD_TIMEOUT_MS (60s after child detected) for the
//     refined render to actually finish. If it stalls, fall back to
//     the parent so the operator never sees a stuck spinner.
//
// Decoupled from useScanOrder by design — this hook only needs a
// render job id, not the scan-order context. Composes at the page
// layer.
// ============================================================================

import { useCallback, useEffect, useRef, useState } from "react";

import {
  getRenderJobStatus,
  type RenderJobResponse,
} from "@/lib/api/highlight-reel";

type TokenGetter = () => Promise<string | null>;

export const POLL_INTERVAL_MS = 3000;
export const REFINEMENT_GRACE_MS = 30_000;
export const CHILD_TIMEOUT_MS = 60_000;

export type RefinedRenderChainStage =
  | "polling_initial"
  | "polling_initial_completed_awaiting_refinement"
  | "polling_child"
  | "settled_initial_canonical"
  | "settled_refined"
  | "settled_failed"
  | "error";

export interface UseRefinedRenderChainState {
  /**
   * The render job currently considered canonical for display.
   * Starts as ``null`` (loading), updates on each successful poll.
   * Use this to surface ``download_url``, ``status``, etc. to the
   * UI — the underlying job id may flip from parent to refined
   * child silently.
   */
  currentJob: RenderJobResponse | null;
  /**
   * Original render job id passed in. Useful for downstream logic
   * (e.g. "edit subtitles" PATCH should target the CURRENT job, not
   * the original — exposed via ``currentJob.id``).
   */
  initialJobId: string;
  /** Discriminator for which lifecycle phase the hook is in. */
  stage: RefinedRenderChainStage;
  /** True while a poll is in flight or scheduled. */
  isPolling: boolean;
  /** Last fetch error, if any. Auto-cleared on next successful poll. */
  error: Error | null;
}

export interface UseRefinedRenderChainOptions {
  /** Override the default 3s polling interval (test-only). */
  pollIntervalMs?: number;
  /** Override the 30s grace period waiting for a refined child. */
  refinementGraceMs?: number;
  /** Override the 60s ceiling on waiting for the child to complete. */
  childTimeoutMs?: number;
  /**
   * Disable polling entirely. Useful when the parent component knows
   * the job is unreachable (e.g. before the operator has triggered
   * a render) — the hook becomes inert until enabled.
   */
  enabled?: boolean;
}

/**
 * Track a render job and its refined child render (if any) until one
 * settles canonical.
 *
 * The hook performs a SILENT SWAP — once a refined child completes,
 * ``currentJob`` flips to point at the child without any UI signal.
 * Per plan §0 leans, this is the v1 behaviour; if operators want a
 * "refined" badge later, layer it on top by comparing
 * ``currentJob.id`` to ``initialJobId``.
 */
export function useRefinedRenderChain(
  initialJobId: string | null,
  getToken: TokenGetter,
  options: UseRefinedRenderChainOptions = {},
): UseRefinedRenderChainState {
  const {
    pollIntervalMs = POLL_INTERVAL_MS,
    refinementGraceMs = REFINEMENT_GRACE_MS,
    childTimeoutMs = CHILD_TIMEOUT_MS,
    enabled = true,
  } = options;

  const [currentJob, setCurrentJob] = useState<RenderJobResponse | null>(null);
  const [stage, setStage] = useState<RefinedRenderChainStage>("polling_initial");
  const [error, setError] = useState<Error | null>(null);
  const [isPolling, setIsPolling] = useState<boolean>(false);

  // Refs so the polling loop doesn't restart every render.
  const targetIdRef = useRef<string | null>(null);
  const stageRef = useRef<RefinedRenderChainStage>("polling_initial");
  const initialCompletedAtRef = useRef<number | null>(null);
  const childDetectedAtRef = useRef<number | null>(null);
  const cancelRef = useRef<boolean>(false);

  // Keep stage ref in sync (state lags behind ref between renders).
  useEffect(() => {
    stageRef.current = stage;
  }, [stage]);

  const advanceStage = useCallback((next: RefinedRenderChainStage) => {
    stageRef.current = next;
    setStage(next);
  }, []);

  const settle = useCallback(
    (job: RenderJobResponse, terminal: RefinedRenderChainStage) => {
      setCurrentJob(job);
      advanceStage(terminal);
      setIsPolling(false);
    },
    [advanceStage],
  );

  useEffect(() => {
    cancelRef.current = false;
    if (!enabled || !initialJobId) {
      return undefined;
    }

    targetIdRef.current = initialJobId;
    initialCompletedAtRef.current = null;
    childDetectedAtRef.current = null;
    advanceStage("polling_initial");
    setIsPolling(true);

    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      if (cancelRef.current) {
        return;
      }
      const targetId = targetIdRef.current;
      if (!targetId) {
        return;
      }

      try {
        const job = await getRenderJobStatus(targetId, getToken);
        if (cancelRef.current) {
          return;
        }
        setError(null);
        setCurrentJob(job);

        const onChild = job.refined_from_render_job_id !== null;

        if (job.status === "failed") {
          settle(job, "settled_failed");
          return;
        }

        if (job.status === "completed") {
          if (onChild) {
            // We were polling the refined child and it completed —
            // the silent swap is final.
            settle(job, "settled_refined");
            return;
          }

          if (job.replaced_by_render_job_id) {
            // Initial parent has produced a refined child; switch
            // target. We may have already completed the parent —
            // remember when so the child timeout starts running.
            targetIdRef.current = job.replaced_by_render_job_id;
            if (childDetectedAtRef.current === null) {
              childDetectedAtRef.current = Date.now();
            }
            advanceStage("polling_child");
          } else {
            // Parent completed but no refined child yet. Wait up to
            // REFINEMENT_GRACE_MS for one to appear.
            if (initialCompletedAtRef.current === null) {
              initialCompletedAtRef.current = Date.now();
            }
            const elapsed =
              Date.now() - (initialCompletedAtRef.current ?? Date.now());
            if (elapsed >= refinementGraceMs) {
              settle(job, "settled_initial_canonical");
              return;
            }
            advanceStage(
              "polling_initial_completed_awaiting_refinement",
            );
          }
        } else if (onChild) {
          // Refined child is still rendering. Bound the wait so a
          // stuck refinement doesn't trap the operator.
          const elapsed =
            Date.now() - (childDetectedAtRef.current ?? Date.now());
          if (elapsed >= childTimeoutMs) {
            // Refined child stalled — leave currentJob set to last
            // good fetch (parent or child mid-render). Caller can
            // detect timeout via ``stage === 'settled_initial_canonical'``
            // when the child never completed.
            settle(job, "settled_initial_canonical");
            return;
          }
        }
      } catch (e) {
        if (cancelRef.current) {
          return;
        }
        setError(e instanceof Error ? e : new Error(String(e)));
        advanceStage("error");
      }

      if (
        !cancelRef.current
        && stageRef.current !== "settled_initial_canonical"
        && stageRef.current !== "settled_refined"
        && stageRef.current !== "settled_failed"
      ) {
        timer = setTimeout(tick, pollIntervalMs);
      } else {
        setIsPolling(false);
      }
    };

    void tick();

    return () => {
      cancelRef.current = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      setIsPolling(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    initialJobId,
    enabled,
    pollIntervalMs,
    refinementGraceMs,
    childTimeoutMs,
  ]);

  return {
    currentJob,
    initialJobId: initialJobId ?? "",
    stage,
    isPolling,
    error,
  };
}
