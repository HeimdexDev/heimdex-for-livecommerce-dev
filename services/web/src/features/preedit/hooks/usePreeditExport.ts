import { useState, useCallback, useEffect, useRef } from "react";
import { submitRender, RenderRateLimitError } from "@/lib/api/shorts-render";
import type { RenderJobResponse } from "@/lib/api/shorts-render";
import { getRenderJobStatus } from "@/lib/api/highlight-reel";
import { exportPremierePackage } from "@/lib/cloud-export";
import { buildPreeditComposition } from "../lib/composition-adapter";
import { buildPremiereRequest } from "../lib/premiere-adapter";
import type { PreeditProject } from "../lib/types";

type TokenGetter = () => Promise<string | null>;
// `rate_limited` is distinct from `failed` so the UI can show
// "wait a moment" instead of a generic error; retrying immediately
// won't help.
type RenderStatus =
  | "idle"
  | "submitting"
  | "queued"
  | "rendering"
  | "completed"
  | "failed"
  | "rate_limited";

const POLL_INTERVAL = 5000;

export function usePreeditExport(
  project: PreeditProject,
  getToken: TokenGetter,
  aspectRatio: "16:9" | "9:16",
) {
  const [renderStatus, setRenderStatus] = useState<RenderStatus>("idle");
  const [renderJob, setRenderJob] = useState<RenderJobResponse | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [premiereError, setPremiereError] = useState<string | null>(null);
  const [isExportingPremiere, setIsExportingPremiere] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  // Poll render job status
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
          setRenderError(updated.error ?? "렌더링에 실패했습니다");
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

  const handleSubmitRender = useCallback(async () => {
    const filledRows = project.rows.filter((r) => r.selectedScene !== null);
    if (filledRows.length === 0) return;

    setRenderStatus("submitting");
    setRenderError(null);
    setRenderJob(null);

    try {
      const spec = buildPreeditComposition(project, aspectRatio);
      const firstVideoId = filledRows[0].selectedScene!.videoId;
      const job = await submitRender(
        JSON.parse(JSON.stringify(spec)),
        firstVideoId,
        project.title || null,
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
        setRenderError(
          err instanceof Error ? err.message : "렌더링 요청에 실패했습니다",
        );
      }
    }
  }, [project, aspectRatio, getToken]);

  const handleExportPremiere = useCallback(
    async (driveMountPath: string) => {
      const filledRows = project.rows.filter((r) => r.selectedScene !== null);
      if (filledRows.length === 0) return;

      setIsExportingPremiere(true);
      setPremiereError(null);

      try {
        const request = buildPremiereRequest(project, driveMountPath);
        await exportPremierePackage(request, getToken);
      } catch (err) {
        setPremiereError(
          err instanceof Error ? err.message : "Premiere 패키지 다운로드에 실패했습니다",
        );
      } finally {
        setIsExportingPremiere(false);
      }
    },
    [project, getToken],
  );

  const reset = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    setRenderStatus("idle");
    setRenderJob(null);
    setRenderError(null);
    setPremiereError(null);
  }, []);

  return {
    renderStatus,
    renderJob,
    renderError,
    submitRender: handleSubmitRender,
    exportPremiere: handleExportPremiere,
    premiereError,
    isExportingPremiere,
    reset,
  };
}
