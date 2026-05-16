// ============================================================================
// useExportBatch — sequential per-clip render orchestrator for the
// auto-shorts edit-clips page.
//
// Owns the state machine for "operator picked N clips → fire N
// ``rerenderFromEdits`` calls → poll each until terminal → expose per-clip
// status + an aggregate progress label". Sequential (not parallel) so the
// per-user render rate limiter (10/hr, server-side) stays friendly.
//
// Per-clip rate-limit / network errors surface in batch state but do NOT
// abort the batch — the remaining clips keep going.
//
// Pure orchestration — no router, no auth coupling beyond the caller-
// supplied token getter. Cancellable via the returned ``cancel()`` (sets
// an internal flag; in-flight POST cannot be aborted but the next-tick
// poll exits cleanly).
// ============================================================================

import { useCallback, useEffect, useRef, useState } from "react";

import {
  RenderRateLimitError,
  getRenderJob,
} from "@/lib/api/shorts-render";
import { rerenderFromEdits } from "@/lib/api/highlight-reel";

import type { ExportItemState } from "../components/ExportShortsButton";

type TokenGetter = () => Promise<string | null>;

interface UseExportBatchOptions {
  /** Polling interval between status checks. Defaults to 3000ms. */
  pollIntervalMs?: number;
  /** Per-clip polling timeout. Defaults to 180_000ms (3min). */
  perClipTimeoutMs?: number;
}

export interface ExportBatchResult {
  /** Per-job export state. Map order is insertion order (= batch order). */
  state: ReadonlyMap<string, ExportItemState>;
  /** True while a batch is currently in flight. */
  isRunning: boolean;
  /** Human-friendly progress label like "(2/3)" or "" when idle. */
  progressLabel: string;
  /** Kick off a batch. Resolves when every clip reaches a terminal state. */
  start: (jobIds: string[]) => Promise<void>;
  /**
   * Co-operative cancel. The current ``rerenderFromEdits`` POST cannot be
   * aborted mid-flight, but the next-tick poll and the next job in the
   * queue both exit cleanly.
   */
  cancel: () => void;
}

const DEFAULT_POLL_MS = 3000;
const DEFAULT_TIMEOUT_MS = 180_000;

export function useExportBatch(
  getToken: TokenGetter,
  options?: UseExportBatchOptions,
): ExportBatchResult {
  const pollIntervalMs = options?.pollIntervalMs ?? DEFAULT_POLL_MS;
  const perClipTimeoutMs = options?.perClipTimeoutMs ?? DEFAULT_TIMEOUT_MS;

  const [state, setState] = useState<Map<string, ExportItemState>>(
    () => new Map(),
  );
  const [isRunning, setIsRunning] = useState(false);
  const [progressLabel, setProgressLabel] = useState("");
  const cancelledRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      cancelledRef.current = true;
    };
  }, []);

  const updateOne = useCallback(
    (jobId: string, next: ExportItemState) => {
      if (!mountedRef.current) return;
      setState((prev) => {
        const out = new Map(prev);
        out.set(jobId, next);
        return out;
      });
    },
    [],
  );

  const pollUntilTerminal = useCallback(
    async (renderJobId: string): Promise<ExportItemState> => {
      const deadline = Date.now() + perClipTimeoutMs;
      while (Date.now() < deadline) {
        if (cancelledRef.current) {
          return { status: "failed", message: "취소됨" };
        }
        await new Promise((resolve) =>
          setTimeout(resolve, pollIntervalMs),
        );
        if (cancelledRef.current) {
          return { status: "failed", message: "취소됨" };
        }
        try {
          const fresh = await getRenderJob(renderJobId, getToken);
          if (fresh.status === "completed") {
            return {
              status: "completed",
              downloadUrl: fresh.download_url,
            };
          }
          if (fresh.status === "failed") {
            return {
              status: "failed",
              message: fresh.error ?? "렌더링 실패",
            };
          }
        } catch {
          // Transient error — next tick retries until the deadline elapses.
        }
      }
      return { status: "failed", message: "시간 초과" };
    },
    [getToken, pollIntervalMs, perClipTimeoutMs],
  );

  const start = useCallback(
    async (jobIds: string[]) => {
      if (jobIds.length === 0) return;
      cancelledRef.current = false;
      setIsRunning(true);
      const initial = new Map<string, ExportItemState>();
      for (const id of jobIds) initial.set(id, { status: "queued" });
      setState(initial);

      let done = 0;
      for (const jobId of jobIds) {
        if (cancelledRef.current) break;
        done += 1;
        if (mountedRef.current) {
          setProgressLabel(`(${done}/${jobIds.length})`);
        }
        updateOne(jobId, { status: "rendering" });
        try {
          const child = await rerenderFromEdits(jobId, getToken);
          // Optimistic: the POST returns the queued child — poll its id,
          // not the parent. Idempotency window may collapse to an existing
          // child, in which case its status is already terminal and the
          // first poll tick returns immediately.
          const final = await pollUntilTerminal(child.id);
          updateOne(jobId, final);
        } catch (err) {
          const message =
            err instanceof RenderRateLimitError
              ? "잠시 후 다시 시도해주세요"
              : err instanceof Error
                ? err.message
                : "실패";
          updateOne(jobId, { status: "failed", message });
        }
      }

      if (mountedRef.current) {
        setIsRunning(false);
        setProgressLabel("");
      }
    },
    [getToken, pollUntilTerminal, updateOne],
  );

  const cancel = useCallback(() => {
    cancelledRef.current = true;
  }, []);

  return { state, isRunning, progressLabel, start, cancel };
}
