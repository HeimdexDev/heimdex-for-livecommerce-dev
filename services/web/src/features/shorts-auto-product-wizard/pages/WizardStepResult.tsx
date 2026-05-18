// figma: 1713:288042  (cache: .figma-cache/1713-288042_phase3_wizard-result.api.json)
// node-name: Component2-6.e AI 쇼츠 생성(생성 결과)
// spec: 외곽 카드 padL/R/T/B=20 radius=10(rounded-card) shadow=card bg=white
// ============================================================================
// Auto-shorts wizard — result screen (Figma 1713:288042).
//
// Single-page result grid replacing the previous "loading + redirect"
// pattern. Per Phase 3 redesign:
//
//   1. Polls parent + children via useScanOrder (3s).
//   2. Header shows "생성된 쇼츠 N개" + 모두 저장/내보내기 (bulk actions).
//   3. Grid renders one ResultCard per child with per-clip status chip
//      (대기/생성/완료/실패) + ⋮ menu + 편집 아이콘.
//   4. Each card's ⋮ + open-in-new affordance lets the operator drill into
//      the existing /edit-clips editor (Phase 5 redesign pending).
//
// Cancel/save/export per-clip backends are not wired yet — see the
// // NOTE(export-backend-tbd) markers below. The whole-order cancel via
// ``useScanOrder.cancel`` is preserved as the row-level cancel action so
// the affordance is functional out of the box.
// ============================================================================

"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import type {
  JobStatusResponse,
  ScanOrderStatusResponse,
  ScanStage,
} from "@/lib/types/shorts-auto-product-wizard";
import { useAuth } from "@/lib/auth";
import { cancelAutoShortJob } from "@/lib/api/shorts-auto-product-wizard";
import { createSavedShort } from "@/lib/api/shorts";
import {
  getRenderJob,
  getShortComposition,
  updateRenderJobTitle,
} from "@/lib/api/shorts-render";

import { ResultCard } from "../components/ResultCard";
import {
  IndexingProgressPanel,
  type IndexingStage,
} from "../components/IndexingProgressPanel";
import { InlineWizardBreadcrumb } from "../components/InlineWizardBreadcrumb";
import type { WizardCriteriaDraft } from "../components/InlineWizardCriteriaPanel";
import type { CriteriaSummary } from "@/lib/types/shorts-auto-product-wizard";
import { useScanOrder } from "../hooks/useScanOrder";
import { useTopHeaderLeftActions } from "@/components/layout/TopHeaderActionsContext";

// Map the backend CriteriaSummary shape to the wizard's WizardCriteriaDraft
// so IndexingProgressPanel can render its option summary badge directly.
// Missing fields fall back to DEFAULT_CRITERIA values.
function summaryFromCriteria(
  c: CriteriaSummary | null | undefined,
): WizardCriteriaDraft | undefined {
  if (!c) return undefined;
  const dist =
    c.product_distribution === "single" || c.product_distribution === "multi"
      ? c.product_distribution
      : "single";
  return {
    length_seconds: c.length_seconds ?? 60,
    requested_count: c.requested_count ?? 5,
    time_range_start_ms: c.time_range_start_ms,
    time_range_end_ms: c.time_range_end_ms,
    product_distribution: dist,
  };
}

const INDEXING_STAGES: ReadonlyArray<IndexingStage> = [
  "enumerating",
  "tracking",
  "assembling",
  "rendering",
];

function mapStageToIndexing(stage: ScanStage | undefined): IndexingStage | null {
  return stage === "enumerating" ||
    stage === "tracking" ||
    stage === "assembling" ||
    stage === "rendering"
    ? stage
    : null;
}

function computeCompletedStages(
  stage: ScanStage | undefined,
): ReadonlyArray<IndexingStage> {
  switch (stage) {
    case "enumeration_done":
    case "tracking":
      return ["enumerating"];
    case "assembling":
      return ["enumerating", "tracking"];
    case "rendering":
      return ["enumerating", "tracking", "assembling"];
    case "preview_ready":
    case "fanned_out":
    case "committed":
    case "done":
      return INDEXING_STAGES;
    default:
      return [];
  }
}

interface Props {
  videoId: string;
  parentJobId: string;
}

const FAILURE_STAGES: ReadonlySet<ScanStage> = new Set<ScanStage>([
  "failed",
  "cancelled",
]);

function isWholeOrderFailed(status: ScanOrderStatusResponse | null): boolean {
  if (!status) return false;
  return FAILURE_STAGES.has(status.parent.stage);
}

export function WizardStepResult({ videoId, parentJobId }: Props) {
  const { getAccessToken } = useAuth();
  const router = useRouter();
  // Breadcrumb (GNB step indicator) — pinned to step 3 for both the
  // loading and result-grid states. Previously the hook only fired
  // through IndexingProgressPanel, which doesn't mount once children
  // arrive, so the breadcrumb disappeared as soon as the grid rendered.
  const breadcrumbSlot = useMemo(
    () => <InlineWizardBreadcrumb currentStep={3} />,
    [],
  );
  useTopHeaderLeftActions(breadcrumbSlot);
  // ``cancel`` from useScanOrder is the whole-order cancel — replaced by
  // per-child cancelAutoShortJob below so a single card's cancel doesn't
  // kill the rest of the batch.
  const { status, error } = useScanOrder(parentJobId, getAccessToken);

  // Local map of user-set render-job titles, keyed by render_job_id. The
  // backend persists the new title via PATCH /api/shorts/render/{id}, but
  // the scan-order poll response doesn't carry it back, so we mirror the
  // value here for immediate UI feedback. The map is intentionally not
  // re-hydrated on mount; reopening the page falls back to the default
  // "쇼츠 N" label until the backend response is extended to include it.
  const [renamedTitles, setRenamedTitles] = useState<Record<string, string>>({});

  const children = status?.children ?? [];
  const childrenTotal = status?.children_total ?? 0;
  const failure = useMemo(() => isWholeOrderFailed(status), [status]);

  const completedCount = useMemo(
    () =>
      children.filter((c: JobStatusResponse) => c.render_status === "completed")
        .length,
    [children],
  );
  const anyCompleted = completedCount > 0;

  const openEditor = (child: JobStatusResponse) => {
    const renderJobId = child.render_job_id;
    const url =
      `/export/shorts/auto/wizard/${encodeURIComponent(videoId)}` +
      `/result/${encodeURIComponent(parentJobId)}/edit-clips` +
      (renderJobId ? `?clip=${encodeURIComponent(renderJobId)}` : "");
    router.push(url);
  };

  // Persist a completed auto-shorts child to the SavedShort library so it
  // shows up in /export/shorts. The wizard creates ShortsRenderJob rows
  // directly; this wraps the render job's input_spec into a SavedShort row
  // (scene_ids + timing) so the saved-shorts list treats it like any other
  // user-saved short. Render must be completed (we need scene_clips from
  // the composition) — disabled caller-side until child.render_status is
  // "completed".
  const saveChildToLibrary = useCallback(
    async (child: JobStatusResponse, ordinal: number): Promise<void> => {
      if (!child.render_job_id) {
        throw new Error("render_job_id missing — cannot resolve composition");
      }
      const composition = await getShortComposition(
        child.render_job_id,
        getAccessToken,
      );
      const sceneClips =
        (composition.composition as { scene_clips?: Array<{ scene_id: string; start_ms?: number; end_ms?: number; timeline_start_ms?: number }> })
          ?.scene_clips ?? [];
      const sceneIds = sceneClips
        .map((c) => c.scene_id)
        .filter((id): id is string => Boolean(id));
      if (sceneIds.length === 0) {
        throw new Error("composition has no scene clips");
      }
      const startMs = sceneClips[0]?.timeline_start_ms ?? 0;
      const lastClip = sceneClips[sceneClips.length - 1];
      const endMs =
        lastClip?.timeline_start_ms != null && lastClip?.end_ms != null && lastClip?.start_ms != null
          ? lastClip.timeline_start_ms + (lastClip.end_ms - lastClip.start_ms)
          : null;
      const compositionTitle =
        (composition.composition as { title?: string | null })?.title ?? null;
      await createSavedShort(
        {
          video_id: videoId,
          scene_ids: sceneIds,
          title: compositionTitle ?? `쇼츠 ${ordinal}`,
          start_ms: startMs,
          end_ms: endMs,
        },
        getAccessToken,
      );
    },
    [getAccessToken, videoId],
  );

  // Trigger a browser download for a single child render job. Pulls the
  // presigned ``download_url`` from the render-job detail endpoint (the
  // poll response doesn't carry it) and opens it via an anchor click —
  // browsers honour the ``download`` attribute on the same-origin or
  // CORS-aware S3 URL the backend returns.
  const downloadChild = useCallback(
    async (child: JobStatusResponse, ordinal: number): Promise<void> => {
      if (!child.render_job_id) {
        throw new Error("render_job_id missing — cannot resolve download URL");
      }
      const job = await getRenderJob(child.render_job_id, getAccessToken);
      if (!job.download_url) {
        throw new Error("download_url not available yet — render not complete?");
      }
      const a = document.createElement("a");
      a.href = job.download_url;
      a.download = `${job.title ?? `shorts_${ordinal}`}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    },
    [getAccessToken],
  );

  const handleSaveCard = useCallback(
    (child: JobStatusResponse, ordinal: number) => {
      void (async () => {
        try {
          await saveChildToLibrary(child, ordinal);
          router.push("/export/shorts");
        } catch (err) {
          // Surface the failure in the console — no toast surface in this
          // page yet. Save errors are rare (composition is fetched fresh
          // from the same render_job already shown on this card).
          console.error("[wizard] save card failed", err);
        }
      })();
    },
    [router, saveChildToLibrary],
  );

  const handleExportCard = useCallback(
    (child: JobStatusResponse, ordinal: number) => {
      void downloadChild(child, ordinal).catch((err) => {
        console.error("[wizard] export card failed", err);
      });
    },
    [downloadChild],
  );

  const handleCancelCard = useCallback(
    (child: JobStatusResponse) => {
      void cancelAutoShortJob(child.job_id, getAccessToken).catch((err) => {
        console.error("[wizard] cancel card failed", err);
      });
    },
    [getAccessToken],
  );

  const handleRenameCard = useCallback(
    (child: JobStatusResponse, ordinal: number) => {
      if (!child.render_job_id) return;
      const currentTitle =
        renamedTitles[child.render_job_id] ?? `쇼츠 ${ordinal}`;
      // window.prompt is intentionally lightweight here — the wizard
      // result page has no dialog primitive of its own and the rename
      // UX is "one-shot text override," not a multi-field form. A custom
      // dialog can replace this when the design lands.
      const next = window.prompt("새 제목을 입력하세요.", currentTitle);
      if (next == null) return;
      const trimmed = next.trim();
      if (trimmed.length === 0 || trimmed === currentTitle) return;
      void (async () => {
        try {
          await updateRenderJobTitle(
            child.render_job_id as string,
            trimmed,
            getAccessToken,
          );
          setRenamedTitles((prev) => ({
            ...prev,
            [child.render_job_id as string]: trimmed,
          }));
        } catch (err) {
          console.error("[wizard] rename card failed", err);
        }
      })();
    },
    [getAccessToken, renamedTitles],
  );

  const handleBulkSave = useCallback(() => {
    void (async () => {
      const targets = children.filter(
        (c) => c.render_status === "completed" && c.render_job_id,
      );
      try {
        for (let i = 0; i < targets.length; i++) {
          await saveChildToLibrary(targets[i], (targets[i].shorts_index ?? i) + 1);
        }
        router.push("/export/shorts");
      } catch (err) {
        console.error("[wizard] bulk save failed", err);
      }
    })();
  }, [children, router, saveChildToLibrary]);

  const handleBulkExport = useCallback(() => {
    void (async () => {
      const targets = children.filter(
        (c) => c.render_status === "completed" && c.render_job_id,
      );
      // Stagger downloads so popup blockers / browser concurrency limits
      // don't drop later clips. 150ms beats the typical concurrent-download
      // throttling without making the operator wait noticeably.
      for (let i = 0; i < targets.length; i++) {
        try {
          await downloadChild(targets[i], (targets[i].shorts_index ?? i) + 1);
        } catch (err) {
          console.error("[wizard] bulk export item failed", err);
        }
        if (i < targets.length - 1) {
          await new Promise((r) => setTimeout(r, 150));
        }
      }
    })();
  }, [children, downloadChild]);

  return (
    <div
      className="mx-auto flex max-w-[1024px] flex-col gap-[20px] p-[24px]"
      data-testid="wizard-step-result"
    >
      <header className="flex items-center justify-between gap-[10px]">
        <div className="flex items-baseline gap-[6px]">
          <h1 className="font-pretendard text-[18px] font-bold tracking-[-0.45px] leading-[1.4] text-neutral-h-800">
            생성된 쇼츠
          </h1>
          <span
            className="font-pretendard text-[14px] font-semibold text-heimdex-navy-500"
            data-testid="result-header-count"
          >
            {childrenTotal}개
          </span>
        </div>
        <div className="flex items-center gap-[10px]">
          <Button
            variant="secondary"
            size="sm"
            disabled={!anyCompleted}
            // Iterates the completed children, POSTs each through
            // createSavedShort, then navigates to /export/shorts. The
            // user explicitly wants the saved-shorts list as the landing
            // surface after a bulk save (per 2026-05-18 spec).
            onClick={handleBulkSave}
            data-testid="result-bulk-save"
          >
            모두 저장하기
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!anyCompleted}
            // Per-completed-child download. Backend doesn't expose a ZIP
            // bundle endpoint, so we stagger the individual presigned
            // downloads with a 150ms gap to keep popup blockers happy.
            onClick={handleBulkExport}
            data-testid="result-bulk-export"
          >
            모두 내보내기
          </Button>
        </div>
      </header>

      {error ? (
        <div
          className="rounded-card bg-red-h-50 p-[12px] font-pretendard text-[14px] text-red-h-500"
          data-testid="wizard-status-error"
        >
          상태 조회 실패: {error.message}
        </div>
      ) : null}

      {failure && status ? <FailureBanner status={status} /> : null}

      {childrenTotal === 0 ? (
        <div data-testid="result-grid-empty">
          <IndexingProgressPanel
            progress={(status?.parent.progress_pct ?? 0) / 100}
            currentStage={mapStageToIndexing(status?.parent.stage)}
            completedStages={computeCompletedStages(status?.parent.stage)}
            criteria={summaryFromCriteria(status?.criteria)}
            videoDurationMs={
              // No dedicated video-duration field on the response yet —
              // fall back to time_range_end_ms (set when the user picked
              // a range in step 1). undefined hides the badge.
              status?.criteria?.time_range_end_ms ?? undefined
            }
          />
        </div>
      ) : (
        // Render exactly `requested_count` slots so the grid reflects the
        // count the user picked in step 1. Children are indexed by
        // `shorts_index`; slots that don't yet have a backing child get a
        // placeholder card (same visual rhythm, no menu) so the layout
        // doesn't reflow as children come in over the polling window.
        (() => {
          const requestedCount = Math.max(
            children.length,
            status?.criteria?.requested_count ?? 0,
          );
          const lengthSeconds = status?.criteria?.length_seconds ?? null;
          const slots = Array.from({ length: requestedCount }, (_, i) =>
            children.find((c) => (c.shorts_index ?? -1) === i) ?? null,
          );
          return (
            <div
              className="flex flex-wrap gap-[20px] rounded-card bg-white p-[20px] shadow-card"
              data-testid="result-grid"
            >
              {slots.map((child, i) => {
                if (!child) {
                  return (
                    <PendingResultCard
                      key={`slot-${i}`}
                      ordinal={i + 1}
                      lengthSeconds={lengthSeconds}
                    />
                  );
                }
                const ordinal = (child.shorts_index ?? i) + 1;
                const renamedTitle =
                  child.render_job_id != null
                    ? renamedTitles[child.render_job_id]
                    : undefined;
                return (
                  <ResultCard
                    key={child.job_id}
                    child={child}
                    videoId={videoId}
                    ordinal={ordinal}
                    lengthSeconds={lengthSeconds}
                    productLabels={child.product_labels ?? []}
                    summary={child.render_summary ?? null}
                    title={renamedTitle ?? null}
                    onRename={() => handleRenameCard(child, ordinal)}
                    onSave={() => handleSaveCard(child, ordinal)}
                    onExport={() => handleExportCard(child, ordinal)}
                    onCancel={() => handleCancelCard(child)}
                    onOpenEditor={() => openEditor(child)}
                  />
                );
              })}
            </div>
          );
        })()
      )}
    </div>
  );
}

// Visual placeholder for a card slot whose backing child job hasn't been
// emitted by the backend yet. Mirrors ResultCard's outer dimensions so
// the grid stays stable as children stream in.
function PendingResultCard({
  ordinal,
  lengthSeconds,
}: {
  ordinal: number;
  lengthSeconds: number | null;
}) {
  const lengthLabel =
    lengthSeconds == null
      ? "—"
      : lengthSeconds % 60 === 0
        ? `${lengthSeconds / 60}분`
        : `${Math.floor(lengthSeconds / 60)}분 ${lengthSeconds % 60}초`;
  return (
    <article
      className="relative flex h-[253px] w-[287px] items-start overflow-clip rounded-card border border-grayscale-100 bg-white opacity-60"
      data-testid={`result-card-${ordinal}-pending`}
    >
      <div className="h-full w-[150px] shrink-0 bg-neutral-h-100" />
      <div className="flex h-full flex-1 flex-col items-end gap-[20px] self-stretch px-[12px] py-[16px]">
        <div className="flex w-full flex-col items-start gap-[20px]">
          <p className="font-pretendard text-[14px] font-semibold tracking-[-0.35px] leading-[1.4] text-grayscale-500">
            쇼츠 {ordinal}
          </p>
          <dl className="flex w-full items-start gap-[10px] font-pretendard text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-500">
            <div className="flex flex-col items-start gap-[10px]">
              <dt>쇼츠 길이</dt>
              <dt>진행률</dt>
            </div>
            <div className="flex flex-col items-start gap-[10px]">
              <dd>{lengthLabel}</dd>
              <dd>0%</dd>
            </div>
          </dl>
        </div>
        <div className="flex-1" />
        <span className="inline-flex items-center justify-center rounded-[4px] bg-grayscale-100 px-[6px] py-[3px] font-pretendard text-[12px] font-semibold tracking-[-0.3px] leading-[1.4] text-grayscale-500">
          대기 중
        </span>
      </div>
    </article>
  );
}

interface FailureBannerProps {
  status: ScanOrderStatusResponse;
}

function FailureBanner({ status }: FailureBannerProps) {
  const parentError = status.parent.error_code
    ? friendlyParentError(status.parent.error_code, status.parent.error_message)
    : null;

  let body: string;
  if (parentError) {
    body = parentError;
  } else if (status.parent.stage === "cancelled") {
    body = "취소되었어요.";
  } else if (
    status.children_total > 0 &&
    status.children_failed === status.children_total
  ) {
    body = "생성 요청한 모든 쇼츠가 실패했어요. 잠시 후 다시 시도해 주세요.";
  } else {
    body = "쇼츠 생성에 실패했어요. 잠시 후 다시 시도해 주세요.";
  }

  return (
    <div
      className="space-y-1 rounded-card border border-red-h-400 bg-red-h-50 p-[16px]"
      data-testid="wizard-failure-state"
    >
      <h2 className="font-pretendard text-[14px] font-semibold text-red-h-500">
        쇼츠 생성에 실패했어요
      </h2>
      <p className="font-pretendard text-[12px] text-red-h-500">{body}</p>
    </div>
  );
}

/**
 * Map known parent-job error codes to user-facing Korean messages.
 * Unknown codes fall back to the raw code + message so a backend
 * regression that adds a new code surfaces visibly rather than
 * disappearing into a generic "오류" blob.
 *
 * Exported for unit tests.
 */
export function friendlyParentError(
  errorCode: string,
  errorMessage: string | null,
): string {
  switch (errorCode) {
    case "proxy_missing":
      return (
        "이 영상은 아직 트랜스코딩이 완료되지 않았어요. 영상 목록에서 " +
        "체크 표시가 뜬 다음 다시 시도해 주세요."
      );
    default:
      return `오류: ${errorCode}${errorMessage ? ` — ${errorMessage}` : ""}`;
  }
}
