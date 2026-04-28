"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { postAutoRender } from "@/lib/api/shorts-auto";
import { getRenderJobStatus, type RenderJobResponse } from "@/lib/api/highlight-reel";
import {
  deleteRenderJob,
  downloadRenderJob,
} from "@/lib/api/shorts-render";
import type { AutoClipResponse, AutoRenderRequest, ScoringModeRequest } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

export type CandidateState =
  | { kind: "candidate" }
  | { kind: "submitting" }
  | { kind: "queued"; job: RenderJobResponse }
  | { kind: "rendering"; job: RenderJobResponse }
  | { kind: "completed"; job: RenderJobResponse }
  | { kind: "failed"; job: RenderJobResponse | null; error: string };

interface CandidateMap {
  [clipKey: string]: CandidateState;
}

interface RenderArgs {
  videoId: string;
  mode: ScoringModeRequest;
  personClusterId: string | null;
  title: string | null;
  clip: AutoClipResponse;
}

interface UseCandidateRenderJobsResult {
  states: CandidateMap;
  /** Convenience accessor with default. */
  getState: (clipKey: string) => CandidateState;
  /** Fire auto-render for a candidate. Flips its state to ``submitting`` → ``queued``/``rendering``/``completed``/``failed``. */
  startRender: (clipKey: string, args: RenderArgs) => Promise<void>;
  /** Trigger a browser download for a ``completed`` job. No-op for other states. */
  download: (clipKey: string, filename: string) => Promise<void>;
  /** Remove a card. If it's render-job-backed, DELETE the backend record. Always clears local state. */
  remove: (clipKey: string) => Promise<void>;
}

const POLL_INTERVAL_MS = 5000;

/**
 * Build a stable key for a candidate clip. ``scene_ids`` is the
 * authoritative composition input — same scene set ⇒ same render
 * deduplication target on the backend (composition_hash window).
 */
export function clipKeyOf(clip: AutoClipResponse): string {
  return clip.scene_ids.join("-");
}

/**
 * Manages the candidate-card → render-job lifecycle for the auto-shorts
 * page. Cards start in ``candidate`` state and the user clicks 다운로드
 * to trigger ``startRender``, which:
 *  1. Sets the card to ``submitting``
 *  2. POSTs ``/api/shorts/auto-render`` with the explicit scene_ids
 *  3. Stores the returned ``RenderJobResponse`` and starts a 5s poll
 *  4. Polls ``GET /api/shorts/render/{id}`` until status terminates
 *     (``completed`` or ``failed``); polling stops automatically.
 *
 * Once ``completed``, ``download`` triggers a browser download via the
 * existing ``downloadRenderJob`` helper. ``remove`` deletes the
 * backend job (if any) and clears the local state.
 *
 * Polling note: a SINGLE interval ticks every ``POLL_INTERVAL_MS`` and
 * fans out to every in-flight job. Avoids per-job intervals piling up
 * when the user submits multiple candidates back-to-back.
 */
export function useCandidateRenderJobs(
  getToken: TokenGetter,
): UseCandidateRenderJobsResult {
  const [states, setStates] = useState<CandidateMap>({});
  const statesRef = useRef(states);
  statesRef.current = states;
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  const setOne = useCallback((clipKey: string, next: CandidateState) => {
    if (!mountedRef.current) return;
    setStates((prev) => ({ ...prev, [clipKey]: next }));
  }, []);

  const tickOnce = useCallback(async () => {
    const current = statesRef.current;
    const inflight: { key: string; jobId: string }[] = [];
    for (const [key, state] of Object.entries(current)) {
      if (state.kind === "queued" || state.kind === "rendering") {
        inflight.push({ key, jobId: state.job.id });
      }
    }
    if (inflight.length === 0) return;

    const updates = await Promise.all(
      inflight.map(async ({ key, jobId }) => {
        try {
          const job = await getRenderJobStatus(jobId, getToken);
          return { key, job };
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          return { key, job: null as RenderJobResponse | null, error: message };
        }
      }),
    );

    if (!mountedRef.current) return;
    setStates((prev) => {
      const next = { ...prev };
      for (const u of updates) {
        if (!next[u.key]) continue;
        if (!u.job) {
          // Treat poll error as transient — keep the prior state so the
          // next tick retries. Don't mark failed unless the backend says so.
          continue;
        }
        if (u.job.status === "completed") {
          next[u.key] = { kind: "completed", job: u.job };
        } else if (u.job.status === "failed") {
          next[u.key] = {
            kind: "failed",
            job: u.job,
            error: u.job.error ?? "Render failed",
          };
        } else if (u.job.status === "rendering") {
          next[u.key] = { kind: "rendering", job: u.job };
        } else {
          // queued or any other in-progress state
          next[u.key] = { kind: "queued", job: u.job };
        }
      }
      return next;
    });
  }, [getToken]);

  // Manage the single shared poll interval. Starts when at least one
  // job is in flight; stops when none remain. Re-runs whenever the
  // states map changes shape.
  useEffect(() => {
    const hasInflight = Object.values(states).some(
      (s) => s.kind === "queued" || s.kind === "rendering",
    );
    if (hasInflight && !pollTimerRef.current) {
      pollTimerRef.current = setInterval(tickOnce, POLL_INTERVAL_MS);
    } else if (!hasInflight && pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    return () => {
      // Don't clear here — let the next mount/unmount run handle it,
      // otherwise we'd thrash the interval on every re-render.
    };
  }, [states, tickOnce]);

  const startRender = useCallback(
    async (clipKey: string, args: RenderArgs) => {
      setOne(clipKey, { kind: "submitting" });
      const body: AutoRenderRequest = {
        video_id: args.videoId,
        mode: args.mode,
        person_cluster_id: args.personClusterId,
        title: args.title,
        scene_ids: args.clip.scene_ids,
      };
      try {
        const job = await postAutoRender(body, getToken);
        if (!mountedRef.current) return;
        // Initial state from server: queued or rendering or completed
        // depending on how fast the worker picked it up.
        if (job.status === "completed") {
          setOne(clipKey, { kind: "completed", job });
        } else if (job.status === "failed") {
          setOne(clipKey, {
            kind: "failed",
            job,
            error: job.error ?? "Render failed",
          });
        } else if (job.status === "rendering") {
          setOne(clipKey, { kind: "rendering", job });
        } else {
          setOne(clipKey, { kind: "queued", job });
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setOne(clipKey, { kind: "failed", job: null, error: message });
      }
    },
    [getToken, setOne],
  );

  const download = useCallback(
    async (clipKey: string, filename: string) => {
      const state = statesRef.current[clipKey];
      if (!state || state.kind !== "completed") return;
      try {
        await downloadRenderJob(state.job.id, filename, getToken);
      } catch (err) {
        // Surface as a transient failure on this card. Keep the job so
        // the user can retry the download.
        const message = err instanceof Error ? err.message : String(err);
        setOne(clipKey, { kind: "failed", job: state.job, error: message });
      }
    },
    [getToken, setOne],
  );

  const remove = useCallback(
    async (clipKey: string) => {
      const state = statesRef.current[clipKey];
      // Always clear locally first so the card disappears immediately.
      if (mountedRef.current) {
        setStates((prev) => {
          const next = { ...prev };
          delete next[clipKey];
          return next;
        });
      }
      if (!state) return;
      const jobId =
        state.kind === "queued" ||
        state.kind === "rendering" ||
        state.kind === "completed" ||
        (state.kind === "failed" && state.job)
          ? (state as { job: RenderJobResponse }).job?.id
          : undefined;
      if (jobId) {
        try {
          await deleteRenderJob(jobId, getToken);
        } catch {
          // Best-effort backend delete; local state already cleared.
        }
      }
    },
    [getToken],
  );

  const getState = useCallback(
    (clipKey: string): CandidateState => states[clipKey] ?? { kind: "candidate" },
    [states],
  );

  return useMemo(
    () => ({ states, getState, startRender, download, remove }),
    [states, getState, startRender, download, remove],
  );
}
