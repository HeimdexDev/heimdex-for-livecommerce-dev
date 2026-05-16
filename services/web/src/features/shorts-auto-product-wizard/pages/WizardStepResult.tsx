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
import { useMemo } from "react";

import { Button } from "@/components/ui/Button";
import type {
  JobStatusResponse,
  ScanOrderStatusResponse,
  ScanStage,
} from "@/lib/types/shorts-auto-product-wizard";
import { useAuth } from "@/lib/auth";

import { ResultCard } from "../components/ResultCard";
import {
  IndexingProgressPanel,
  type IndexingStage,
} from "../components/IndexingProgressPanel";
import type { WizardCriteriaDraft } from "../components/InlineWizardCriteriaPanel";
import type { CriteriaSummary } from "@/lib/types/shorts-auto-product-wizard";
import { useScanOrder } from "../hooks/useScanOrder";

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
  const { status, error, cancel } = useScanOrder(parentJobId, getAccessToken);

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
            // NOTE(export-backend-tbd): bulk save endpoint TBD — wired
            // through Phase 4 once the saved-shorts API ships.
            onClick={() => {
              /* TBD */
            }}
            data-testid="result-bulk-save"
          >
            모두 저장하기
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!anyCompleted}
            // NOTE(export-backend-tbd): bulk export endpoint TBD.
            onClick={() => {
              /* TBD */
            }}
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
        <div
          className="flex flex-wrap gap-[20px] rounded-card bg-white p-[20px] shadow-card"
          data-testid="result-grid"
        >
          {children.map((child) => {
            const ordinal = (child.shorts_index ?? 0) + 1;
            return (
              <ResultCard
                key={child.job_id}
                child={child}
                ordinal={ordinal}
                lengthSeconds={null}
                productLabels={child.product_labels ?? []}
                summary={child.render_summary ?? null}
                // NOTE(export-backend-tbd): rename/save/export per-clip
                // endpoints not wired. Cancel falls through to the
                // whole-order cancel — Figma per-card cancel UX maps to
                // the order-level POST until a per-child endpoint lands.
                onRename={() => {
                  /* TBD */
                }}
                onSave={() => {
                  /* TBD */
                }}
                onExport={() => {
                  /* TBD */
                }}
                onCancel={() => void cancel()}
                onOpenEditor={() => openEditor(child)}
              />
            );
          })}
        </div>
      )}
    </div>
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
