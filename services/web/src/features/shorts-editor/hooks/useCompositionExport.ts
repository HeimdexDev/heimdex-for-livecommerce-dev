import { useState, useCallback, useRef, useEffect } from "react";
import {
  submitRender,
  RenderRateLimitError,
  type RenderJobResponse,
} from "@/lib/api/shorts-render";
import { getRenderJobStatus } from "@/lib/api/highlight-reel";
import type { EditorState } from "../lib/types";
import { buildCompositionSpec } from "../lib/composition-builder";

// `rate_limited` is distinct from `failed` so the UI can show a
// "wait a moment" message instead of a generic error — retrying
// immediately won't help, so we don't want the user to mash the button.
export type RenderStatus =
  | "idle"
  | "submitting"
  | "queued"
  | "rendering"
  | "completed"
  | "failed"
  | "rate_limited";

const POLL_INTERVAL = 5000;

interface UseCompositionExportOptions {
  state: EditorState;
  title: string;
  getToken: () => Promise<string | null>;
}

export function useCompositionExport({ state, title, getToken }: UseCompositionExportOptions) {
  const [renderStatus, setRenderStatus] = useState<RenderStatus>("idle");
  const [renderJob, setRenderJob] = useState<RenderJobResponse | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Poll for job status
  useEffect(() => {
    if (renderStatus !== "queued" && renderStatus !== "rendering") {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }

    if (!renderJob) return;

    pollRef.current = setInterval(async () => {
      try {
        const updated = await getRenderJobStatus(renderJob.id, getToken);
        setRenderJob(updated);

        if (updated.status === "completed") {
          setRenderStatus("completed");
        } else if (updated.status === "failed") {
          setRenderStatus("failed");
          setRenderError(updated.error ?? "렌더링 실패");
        } else if (updated.status === "rendering") {
          setRenderStatus("rendering");
        }
      } catch {
        // Polling failure — keep trying
      }
    }, POLL_INTERVAL);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [renderStatus, renderJob?.id, getToken]);

  const submitComposition = useCallback(async () => {
    if (state.clips.length === 0) return;

    setRenderStatus("submitting");
    setRenderError(null);
    setRenderJob(null);

    try {
      const spec = buildCompositionSpec(state, title || null);
      const job = await submitRender(
        JSON.parse(JSON.stringify(spec)),
        state.videoId,
        title || null,
        getToken,
      );
      setRenderJob(job);
      setRenderStatus("queued");
    } catch (err) {
      if (err instanceof RenderRateLimitError) {
        setRenderStatus("rate_limited");
        setRenderError(err.message);
      } else {
        setRenderStatus("failed");
        setRenderError(err instanceof Error ? err.message : "렌더링 제출 실패");
      }
    }
  }, [state, title, getToken]);

  const reset = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    setRenderStatus("idle");
    setRenderJob(null);
    setRenderError(null);
  }, []);

  return {
    renderStatus,
    renderJob,
    renderError,
    submitComposition,
    reset,
  };
}
