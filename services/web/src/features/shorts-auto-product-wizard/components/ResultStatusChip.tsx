"use client";

import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";
import { cn } from "@/lib/utils";

export type ResultChipState = "queued" | "working" | "done" | "failed";

export function deriveResultChipState(child: JobStatusResponse): ResultChipState {
  if (child.stage === "failed" || child.stage === "cancelled") return "failed";
  if (child.render_status === "completed") return "done";
  if (
    child.stage === "assembling" ||
    child.stage === "rendering" ||
    child.render_status === "rendering"
  ) {
    return "working";
  }
  return "queued";
}

const STATE_LABEL: Record<ResultChipState, string> = {
  queued: "대기 중",
  working: "생성 중",
  done: "완료",
  failed: "실패",
};

const STATE_CLASS: Record<ResultChipState, string> = {
  queued: "bg-neutral-h-100 text-neutral-h-500",
  working: "bg-amber-h-50 text-amber-h-500",
  done: "bg-green-h-50 text-green-h-500",
  failed: "bg-red-h-50 text-red-h-500",
};

interface Props {
  state: ResultChipState;
  className?: string;
}

export function ResultStatusChip({ state, className }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-[6px] px-[8px] py-[3px] font-pretendard text-[12px] font-medium tracking-[-0.3px] leading-[1.4]",
        STATE_CLASS[state],
        className,
      )}
      data-testid={`result-status-chip-${state}`}
    >
      {STATE_LABEL[state]}
    </span>
  );
}
