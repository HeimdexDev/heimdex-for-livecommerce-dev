// ============================================================================
// Center "AI is working" panel for the auto-shorts loading screen. Big
// spinner + Korean copy + an opt-in 전체 취소 ghost button. Pure
// presentational — caller wires onCancel to useScanOrder.cancel().
// ============================================================================

"use client";

import { cn } from "@/lib/utils";

interface Props {
  /**
   * Cancel callback. When omitted, the cancel affordance is hidden — used
   * for terminal states where cancellation is no longer meaningful.
   */
  onCancel?: () => void;
  className?: string;
}

export function LoadingShortsSpinner({ onCancel, className }: Props) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 p-8 text-center",
        className,
      )}
      data-testid="loading-shorts-spinner"
    >
      <div
        className="h-12 w-12 animate-spin rounded-full border-2 border-gray-200 border-b-indigo-500"
        role="status"
        aria-label="쇼츠 생성 중"
      />
      <div className="space-y-1">
        <p className="text-base font-semibold text-gray-900">
          AI가 쇼츠를 생성하고 있어요
        </p>
        <p className="text-sm text-gray-500">평균 10초 정도 소요됩니다.</p>
      </div>
      {onCancel ? (
        <button
          type="button"
          onClick={onCancel}
          className="mt-2 text-xs text-gray-500 underline-offset-2 hover:text-red-700 hover:underline"
          data-testid="loading-shorts-spinner-cancel"
        >
          전체 취소
        </button>
      ) : null}
    </div>
  );
}
