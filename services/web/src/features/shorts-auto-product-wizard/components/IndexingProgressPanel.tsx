// figma: 1713:288103  (cache: .figma-cache/1713-288103_phase2_wizard-indexing.api.json)
// node-name: Component2-6.b AI 쇼츠 생성(인덱싱 중)
// spec: card padL/R/T/B=20 radius=10(rounded-card) shadow=card | pill radius=999(rounded-full) padL/R=16 padT/B=12
// spec: percent 16/600 (Q4 Figma 채택, was 48/600) | connector 31×4 (StageConnectorDots)
// ============================================================================
// Inline-wizard Step 3 (인덱싱 진행) panel — purely presentational. Renders the
// 4-stage pipeline + progress percent + ETA per Figma 1713:288103. Stage
// labels map to backend ``ScanStage`` values:
//
//   enumerating → "분석 중"
//   tracking    → "제품 확인"
//   assembling  → "분류 중"
//   rendering   → "마무리 중"
//
// The mount condition is owned by the caller (the wizard container or
// result page). This component takes the derived ``progress``,
// ``currentStage`` and ``completedStages`` as props so it stays stateless.
// ============================================================================

"use client";

import { Check } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/figma-index";
import { useTopHeaderLeftActions } from "@/components/layout/TopHeaderActionsContext";
import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

import { InlineWizardBreadcrumb } from "./InlineWizardBreadcrumb";
import type { WizardCriteriaDraft } from "./InlineWizardCriteriaPanel";
import { StageConnectorDots } from "./StageConnectorDots";

export type IndexingStage =
  | "enumerating"
  | "tracking"
  | "assembling"
  | "rendering";

const STAGES: ReadonlyArray<{ id: IndexingStage; label: string }> = [
  { id: "enumerating", label: "분석 중" },
  { id: "tracking", label: "제품 확인" },
  { id: "assembling", label: "분류 중" },
  { id: "rendering", label: "마무리 중" },
];

interface Props {
  // criteria + videoDurationMs are optional so the result-page can mount
  // this panel without the wizard-criteria context (no summary chip / 다음
  // button — the right cluster is hidden entirely when either is omitted).
  criteria?: WizardCriteriaDraft;
  videoDurationMs?: number;
  /** Overall progress in [0, 1]. */
  progress: number;
  /** The currently active stage, or null if queued. */
  currentStage: IndexingStage | null;
  /** Stages already finished, in pipeline order. */
  completedStages?: ReadonlyArray<IndexingStage>;
  /** Optional ETA in seconds. Hidden when undefined. */
  estimatedRemainingSeconds?: number;
}

function distributionLabel(value: WizardCriteriaDraft["product_distribution"]) {
  return value === "single" ? "상품별 쇼츠" : "통합 쇼츠";
}

function summaryChip(
  criteria: WizardCriteriaDraft,
  durationMs: number,
): string {
  const start = criteria.time_range_start_ms ?? 0;
  const end = criteria.time_range_end_ms ?? durationMs;
  return [
    distributionLabel(criteria.product_distribution),
    `${formatVideoTimestampHMS(start)} - ${formatVideoTimestampHMS(end)}`,
    `${criteria.length_seconds}초 길이`,
    `${criteria.requested_count}개 생성`,
  ].join(" · ");
}

function clampPercent(progress: number): number {
  if (Number.isNaN(progress)) return 0;
  return Math.max(0, Math.min(100, Math.round(progress * 100)));
}

export function IndexingProgressPanel({
  criteria,
  videoDurationMs,
  progress,
  currentStage,
  completedStages = [],
  estimatedRemainingSeconds,
}: Props) {
  const percent = clampPercent(progress);
  const completedSet = new Set(completedStages);

  // Step indicator lives in the global TopHeader (GNB) per Figma 1602:36766.
  const headerSlot = useMemo(
    () => <InlineWizardBreadcrumb currentStep={3} />,
    [],
  );
  useTopHeaderLeftActions(headerSlot);

  return (
    <div className="space-y-[20px] font-pretendard">
      <div className="space-y-[40px] rounded-card bg-white p-[20px] shadow-card">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-[20px] font-semibold tracking-[-0.5px] text-grayscale-800">
            AI 쇼츠 생성
          </h2>
          {criteria && videoDurationMs != null ? (
            <div className="flex items-center gap-[12px]">
              <span
                className="rounded-full bg-neutral-h-50 px-[12px] py-[6px] text-[12px] font-medium text-grayscale-500"
                data-testid="indexing-summary-chip"
              >
                {summaryChip(criteria, videoDurationMs)}
              </span>
              <Button variant="primary" size="sm" disabled>
                다음
              </Button>
            </div>
          ) : null}
        </div>

        <ol
          className="flex items-center gap-[12px]"
          data-testid="indexing-stage-list"
          aria-label="쇼츠 생성 파이프라인"
        >
          {STAGES.map((stage, i) => {
            const isCompleted = completedSet.has(stage.id);
            const isActive = !isCompleted && currentStage === stage.id;
            const state = isCompleted
              ? "completed"
              : isActive
                ? "active"
                : "queued";
            return (
              <li
                key={stage.id}
                className="flex flex-1 items-center gap-[12px]"
              >
                <span
                  className={cn(
                    "flex flex-1 items-center justify-center gap-[8px] rounded-full px-[16px] py-[12px] text-[14px] font-semibold tracking-[-0.35px] transition",
                    isCompleted &&
                      "bg-heimdex-navy-600 text-white",
                    isActive &&
                      "border-2 border-heimdex-navy-500 bg-white text-heimdex-navy-500",
                    state === "queued" &&
                      "bg-neutral-h-50 text-grayscale-500",
                  )}
                  data-testid={`indexing-stage-${stage.id}`}
                  data-state={state}
                >
                  {isCompleted ? (
                    <Check
                      className="h-[16px] w-[16px]"
                      strokeWidth={3}
                      aria-hidden="true"
                    />
                  ) : null}
                  {isActive ? (
                    <span
                      className="inline-flex h-[16px] w-[16px] animate-spin"
                      aria-hidden="true"
                    >
                      <span className="block h-full w-full rounded-full border-2 border-neutral-h-100 border-t-heimdex-navy-500" />
                    </span>
                  ) : null}
                  <span>{stage.label}</span>
                </span>
                {i < STAGES.length - 1 ? (
                  <StageConnectorDots precedingState={state} />
                ) : null}
              </li>
            );
          })}
        </ol>

        <div className="flex flex-col items-center gap-[8px] pb-[20px] pt-[12px]">
          <p
            className="text-[16px] font-semibold leading-[1.4] tracking-[-0.4px] text-heimdex-navy-500"
            data-testid="indexing-progress-percent"
          >
            {percent}%
          </p>
          {estimatedRemainingSeconds != null ? (
            <p
              className="text-[14px] font-medium tracking-[-0.35px] text-neutral-h-600"
              data-testid="indexing-progress-eta"
            >
              약 {Math.max(0, Math.round(estimatedRemainingSeconds))}초
              남았습니다.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
