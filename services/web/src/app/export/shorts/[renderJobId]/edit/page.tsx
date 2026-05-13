// ============================================================================
// /export/shorts/[renderJobId]/edit — single-render editor entry point.
//
// Launched from the SavedShortsPage "Edit" button (Phase 4). Resolves
// the render's ``video_id`` (a required EditClipsPage prop) and
// follows the refinement chain if the URL points at a stale
// intermediate render — operators with bookmarked editor URLs land
// on the current canonical leaf without manual intervention.
//
// Three terminal states:
//   1. Render not found / not owned → redirect to /export/shorts.
//   2. Render is an intermediate (``effective_render_job_id`` set)
//      → redirect to the leaf's edit URL.
//   3. Render is a leaf → mount EditClipsPage in single mode.
//
// Loose-coupling: this file is the ONLY consumer of EditClipsPage
// outside the wizard route. SavedShortsPage navigates here via a
// plain ``next/link`` — no direct import of wizard internals.
// ============================================================================

"use client";

import dynamic from "next/dynamic";
import { useParams, useRouter } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";
import { getRenderJob } from "@/lib/api/shorts-render";
import type { RenderJobResponse } from "@/lib/api/highlight-reel";

const EditClipsPage = dynamic(
  () =>
    import("@/features/shorts-auto-product-wizard/pages/EditClipsPage").then(
      (m) => m.EditClipsPage,
    ),
  { ssr: false },
);

type LoadState =
  | { kind: "loading" }
  | { kind: "redirecting" }
  | { kind: "ready"; render: RenderJobResponse }
  | { kind: "error"; message: string };

export default function SavedShortsEditRoute() {
  const params = useParams<{ renderJobId: string }>();
  const renderJobId = params?.renderJobId ?? "";
  const router = useRouter();
  const { getAccessToken } = useAuth();

  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!renderJobId) {
      router.replace("/export/shorts");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const render = await getRenderJob(renderJobId, getAccessToken);
        if (cancelled) return;
        // Stale id: bounce to the leaf so the editor opens on the
        // canonical row. ``replace`` (not ``push``) avoids leaving a
        // dead history entry behind.
        if (
          render.effective_render_job_id &&
          render.effective_render_job_id !== render.id
        ) {
          setState({ kind: "redirecting" });
          router.replace(
            `/export/shorts/${encodeURIComponent(render.effective_render_job_id)}/edit`,
          );
          return;
        }
        setState({ kind: "ready", render });
      } catch (err) {
        if (cancelled) return;
        // 404 / not-owned / network: bounce back to the list. The
        // list will show whatever the user actually has access to;
        // this avoids a blank "edit unknown short" surface.
        const message =
          err instanceof Error ? err.message : "Unknown error";
        setState({ kind: "error", message });
        router.replace("/export/shorts");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [renderJobId, getAccessToken, router]);

  if (state.kind !== "ready") {
    return (
      <div
        className="flex min-h-screen items-center justify-center"
        data-testid="saved-shorts-edit-loading"
      >
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      }
    >
      <EditClipsPage
        mode="single"
        videoId={state.render.video_id}
        renderJobId={state.render.id}
      />
    </Suspense>
  );
}
