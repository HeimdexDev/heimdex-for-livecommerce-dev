"use client";

import { SquareArrowOutUpRight } from "lucide-react";

import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";
import { cn } from "@/lib/utils";

import {
  ResultStatusChip,
  deriveResultChipState,
} from "./ResultStatusChip";
import { ResultCardMenu } from "./ResultCardMenu";

interface Props {
  child: JobStatusResponse;
  /** 1-based ordinal shown as "쇼츠 N". Falls back to ``shorts_index + 1``. */
  ordinal: number;
  /** Original criteria.length_seconds for the parent scan order. */
  lengthSeconds?: number | null;
  /** Up to 2 product names to display as overlay chips. */
  productLabels?: string[];
  // figma: 1699:252725 (쇼츠 카드) — 우측 컬럼 요약 텍스트. 50자(공백 포함) 초과 시 ellipsis truncate.
  summary?: string | null;
  onRename: () => void;
  onSave?: () => void;
  onExport?: () => void;
  onCancel: () => void;
  onOpenEditor: () => void;
}

const SUMMARY_MAX_CHARS = 50;

function formatLength(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s}초`;
  if (s === 0) return `${m}분`;
  return `${m}분 ${s}초`;
}

function truncateSummary(text: string | null | undefined): string {
  if (!text) return "";
  if (text.length <= SUMMARY_MAX_CHARS) return text;
  return `${text.slice(0, SUMMARY_MAX_CHARS)}…`;
}

export function ResultCard({
  child,
  ordinal,
  lengthSeconds,
  productLabels = [],
  summary,
  onRename,
  onSave,
  onExport,
  onCancel,
  onOpenEditor,
}: Props) {
  const state = deriveResultChipState(child);
  const isCompleted = state === "done";
  const progressPct = Math.max(0, Math.min(100, Math.round(child.progress_pct)));
  const summaryText = truncateSummary(summary);

  return (
    <article
      className="flex h-[253px] w-[287px] gap-[10px] rounded-card bg-white p-[10px] shadow-card"
      data-testid={`result-card-${ordinal}`}
    >
      <div className="relative h-full aspect-[9/16] shrink-0 overflow-hidden rounded-[8px] bg-grayscale-800">
        {productLabels.length > 0 ? (
          <div className="absolute left-[8px] bottom-[8px] flex flex-wrap gap-[4px]">
            {productLabels.slice(0, 2).map((label, i) => (
              <span
                key={`${label}-${i}`}
                className="rounded-[4px] bg-black/60 px-[6px] py-[2px] font-pretendard text-[10px] font-medium text-white"
              >
                {label}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="flex h-full flex-1 flex-col justify-between py-[4px]">
        <p
          className={cn(
            "font-pretendard text-[14px] font-semibold tracking-[-0.35px] leading-[1.4]",
            isCompleted ? "text-grayscale-800" : "text-grayscale-800",
          )}
          data-testid="result-card-title"
        >
          쇼츠 {ordinal}
        </p>

        <dl className="flex flex-col gap-[8px]">
          <div className="flex items-baseline justify-between">
            <dt className="font-pretendard text-[12px] font-medium text-grayscale-500">
              쇼츠 길이
            </dt>
            <dd className="font-pretendard text-[12px] font-medium text-grayscale-800">
              {formatLength(lengthSeconds)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between">
            <dt className="font-pretendard text-[12px] font-medium text-grayscale-500">
              진행률
            </dt>
            <dd
              className="font-pretendard text-[12px] font-medium text-grayscale-800"
              data-testid="result-card-progress"
            >
              {progressPct}%
            </dd>
          </div>
        </dl>

        {summaryText ? (
          <p
            className="font-pretendard text-[12px] font-medium leading-[1.4] text-grayscale-600"
            data-testid="result-card-summary"
          >
            {summaryText}
          </p>
        ) : null}

        <div className="flex items-center justify-between">
          <ResultStatusChip state={state} />
        </div>
      </div>

      <div className="flex h-full w-[24px] shrink-0 flex-col items-center gap-[8px] py-[4px]">
        <ResultCardMenu
          isCompleted={isCompleted}
          onRename={onRename}
          onSave={onSave}
          onExport={onExport}
          onCancel={onCancel}
        />
        <button
          type="button"
          aria-label="편집 페이지 열기"
          data-testid="result-card-open-editor"
          onClick={onOpenEditor}
          disabled={!isCompleted}
          className="inline-flex h-[24px] w-[24px] items-center justify-center rounded-[6px] text-grayscale-500 hover:bg-neutral-h-50 disabled:text-neutral-h-300 disabled:hover:bg-transparent"
        >
          <SquareArrowOutUpRight className="h-[16px] w-[16px]" />
        </button>
      </div>
    </article>
  );
}
