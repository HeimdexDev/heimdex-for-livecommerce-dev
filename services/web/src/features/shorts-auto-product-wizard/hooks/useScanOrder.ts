// ============================================================================
// Scan-order lifecycle hook for the wizard.
//
// One responsibility: take a created parent_job_id, poll its aggregate
// status every 3s, expose the current snapshot + a stop signal. The
// criteria step uses ``createScanOrder`` directly (one-shot mutation);
// this hook subscribes to the resulting parent.
//
// Polling cadence is 3s (locked in plan §4.4 — codex pushback against
// the original 10s throttle for the rendering stage; child stages can
// transition queued→assembling→done faster than 10s).
// ============================================================================

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelScanOrder,
  getScanOrderStatus,
} from "@/lib/api/shorts-auto-product-wizard";
import type { ScanOrderStatusResponse } from "@/lib/types/shorts-auto-product-wizard";
import { isTerminalStage } from "@/lib/types/shorts-auto-product-wizard";

type TokenGetter = () => Promise<string | null>;

const POLL_INTERVAL_MS = 3000;

export interface UseScanOrderState {
  status: ScanOrderStatusResponse | null;
  error: Error | null;
  isPolling: boolean;
}

export interface UseScanOrderResult extends UseScanOrderState {
  cancel: () => Promise<void>;
}

/**
 * Subscribe to a scan order's aggregate status.
 *
 * Polls every 3s until ALL of:
 *   - parent stage is terminal (done / committed / failed / cancelled)
 *   - every child stage is terminal
 *
 * Tests can override the interval by passing ``pollIntervalMs``.
 */
export function useScanOrder(
  parentJobId: string | null,
  tokenGetter: TokenGetter,
  options?: { pollIntervalMs?: number },
): UseScanOrderResult {
  const interval = options?.pollIntervalMs ?? POLL_INTERVAL_MS;
  const [state, setState] = useState<UseScanOrderState>({
    status: null,
    error: null,
    isPolling: false,
  });
  // Use a ref to track latest state in the polling closure without
  // re-creating the interval on each render.
  const stateRef = useRef(state);
  stateRef.current = state;

  // Determine whether polling should continue based on the latest
  // status. Pure function — no side effects.
  const shouldKeepPolling = useCallback(
    (status: ScanOrderStatusResponse): boolean => {
      if (!isTerminalStage(status.parent.stage)) return true;
      // Parent terminal but children still active → keep polling so
      // the UI sees their final stages.
      return status.children.some((c) => !isTerminalStage(c.stage));
    },
    [],
  );

  useEffect(() => {
    if (!parentJobId) {
      setState({ status: null, error: null, isPolling: false });
      return;
    }

    let cancelled = false;
    setState((prev) => ({ ...prev, isPolling: true, error: null }));

    const poll = async () => {
      try {
        const next = await getScanOrderStatus(parentJobId, tokenGetter);
        if (cancelled) return;
        const keepGoing = shouldKeepPolling(next);
        setState({
          status: next,
          error: null,
          isPolling: keepGoing,
        });
        if (keepGoing) {
          timerHandle = window.setTimeout(poll, interval);
        }
      } catch (err) {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          error: err instanceof Error ? err : new Error(String(err)),
          isPolling: false,
        }));
      }
    };

    let timerHandle: number | undefined;
    void poll();

    return () => {
      cancelled = true;
      if (timerHandle !== undefined) {
        window.clearTimeout(timerHandle);
      }
    };
  }, [parentJobId, tokenGetter, interval, shouldKeepPolling]);

  const cancel = useCallback(async () => {
    if (!parentJobId) return;
    await cancelScanOrder(parentJobId, tokenGetter);
    // Trigger a fresh status read so the UI updates fast (rather
    // than waiting for the next 3s tick).
    try {
      const refreshed = await getScanOrderStatus(parentJobId, tokenGetter);
      setState({ status: refreshed, error: null, isPolling: false });
    } catch {
      // Ignore — the next poll cycle will surface any error.
    }
  }, [parentJobId, tokenGetter]);

  return { ...state, cancel };
}
