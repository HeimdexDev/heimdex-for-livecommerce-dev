// ============================================================================
// Determinate progress UI for the auto-shorts loading screen.
//
// Renders a percentage bar driven by ``completed / total`` plus one chip
// per child showing live per-clip state (queued / rendering / ready /
// failed). Used when ``children_total > 0`` — pre-fan-out the screen
// still shows the indeterminate LoadingShortsSpinner instead.
//
// Pure presentational. Caller (WizardStepResult) wires ``children`` from
// the polled status and ``onCancel`` to ``useScanOrder.cancel()``.
// ============================================================================

"use client";

import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";
import { cn } from "@/lib/utils";

interface Props {
  children: JobStatusResponse[];
  /** ScanOrderStatusResponse.children_total — used as the denominator
   *  so the bar reflects intended count even before fan-out populates
   *  the children array fully. */
  childrenTotal: number;
  /**
   * Cancel callback. When omitted (e.g., redirect has fired), the
   * cancel affordance is hidden to avoid a doomed POST race.
   */
  onCancel?: () => void;
  className?: string;
}

type ChipState = "queued" | "working" | "ready" | "failed";

function chipStateFor(child: JobStatusResponse): ChipState {
  if (child.stage === "failed" || child.stage === "cancelled") return "failed";
  if (child.render_status === "completed") return "ready";
  if (
    child.stage === "assembling" ||
    child.stage === "rendering" ||
    child.render_status === "rendering"
  ) {
    return "working";
  }
  return "queued";
}

const CHIP_LABEL: Record<ChipState, string> = {
  queued: "대기 중",
  working: "렌더링 중",
  ready: "완료",
  failed: "실패",
};

const CHIP_CLASSES: Record<ChipState, string> = {
  queued: "bg-gray-100 text-gray-600 ring-1 ring-gray-200",
  working: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
  ready: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-1 ring-red-200",
};

export function LoadingShortsProgress({
  children,
  childrenTotal,
  onCancel,
  className,
}: Props) {
  const safeTotal = Math.max(0, Math.floor(childrenTotal));
  const renderedCount = children.filter(
    (c) => c.render_status === "completed",
  ).length;
  const failedCount = children.filter(
    (c) => c.stage === "failed" || c.stage === "cancelled",
  ).length;
  const pct =
    safeTotal === 0
      ? 0
      : Math.min(100, Math.round((renderedCount / safeTotal) * 100));

  // Sort by shorts_index so chip order matches the left-rail skeleton
  // order. Stable for nulls — fall back to job_id.
  const sortedChildren = [...children].sort((a, b) => {
    const ai = a.shorts_index ?? Number.POSITIVE_INFINITY;
    const bi = b.shorts_index ?? Number.POSITIVE_INFINITY;
    if (ai !== bi) return ai - bi;
    return a.job_id.localeCompare(b.job_id);
  });

  return (
    <div
      className={cn(
        "flex w-full flex-col items-center gap-5 p-8 text-center",
        className,
      )}
      data-testid="loading-shorts-progress"
    >
      <div className="space-y-1">
        <p className="text-base font-semibold text-gray-900">
          쇼츠 {renderedCount}/{safeTotal}개 준비 중
        </p>
        <p className="text-sm text-gray-500">
          {renderedCount === safeTotal && safeTotal > 0
            ? "완료! 편집 화면으로 이동합니다…"
            : "AI가 쇼츠를 생성하고 있어요. 평균 10초 정도 소요됩니다."}
        </p>
      </div>

      <div
        className="h-2 w-full max-w-md overflow-hidden rounded-full bg-gray-100"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="쇼츠 생성 진행률"
        data-testid="loading-shorts-progress-bar"
      >
        <div
          className="h-full rounded-full bg-indigo-500 transition-[width] duration-300 ease-out"
          style={{ width: `${pct}%` }}
          data-testid="loading-shorts-progress-fill"
        />
      </div>

      {failedCount > 0 ? (
        <p
          className="text-xs text-gray-500"
          data-testid="loading-shorts-progress-failed"
        >
          완료 {renderedCount} · 실패 {failedCount}
        </p>
      ) : null}

      {sortedChildren.length > 0 ? (
        <ul
          className="flex flex-wrap justify-center gap-2"
          data-testid="loading-shorts-progress-chips"
        >
          {sortedChildren.map((child) => {
            const state = chipStateFor(child);
            return (
              <li
                key={child.job_id}
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs font-medium",
                  CHIP_CLASSES[state],
                )}
                data-testid="loading-shorts-progress-chip"
                data-state={state}
              >
                <span className="font-semibold">
                  {child.shorts_index ?? "?"}
                </span>
                <span className="ml-1">{CHIP_LABEL[state]}</span>
              </li>
            );
          })}
        </ul>
      ) : null}

      {onCancel ? (
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-gray-500 underline-offset-2 hover:text-red-700 hover:underline"
          data-testid="loading-shorts-progress-cancel"
        >
          전체 취소
        </button>
      ) : null}
    </div>
  );
}
