// ============================================================================
// Inline-wizard step 2-1 (인덱싱 진행) progress panel.
//
// 2026-05-19 redesign: drop the pill-style stage chips that wrapped
// their inline labels vertically when the wrapper width was squeezed.
// New layout is a step indicator — circle + label-below — with a
// single horizontal connector line that passes UNDER the circles
// (z-index trick) so there is no visible gap between line and circle.
//
// Stage labels map to backend ``ScanStage`` values:
//   enumerating → "분석 중"
//   tracking    → "상품 확인"
//   assembling  → "분류 중"
//   rendering   → "마무리 중"
//
// The mount condition is owned by the caller. This component takes
// the derived ``progress``, ``currentStage`` and ``completedStages``
// as props so it stays stateless.
// ============================================================================

"use client";

import { Button } from "@/components/ui/figma-index";
import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

import type { WizardCriteriaDraft } from "./InlineWizardCriteriaPanel";

const NAVY = "#234C77";
const GREEN_CHECK = "#3FB675";
const QUEUED_GRAY = "#E5E7EB";

export type IndexingStage =
  | "enumerating"
  | "tracking"
  | "assembling"
  | "rendering";

const STAGES: ReadonlyArray<{ id: IndexingStage; label: string }> = [
  { id: "enumerating", label: "분석 중" },
  { id: "tracking", label: "상품 확인" },
  { id: "assembling", label: "분류 중" },
  { id: "rendering", label: "마무리 중" },
];

interface Props {
  criteria?: WizardCriteriaDraft;
  videoDurationMs?: number;
  /** Overall progress in [0, 1]. */
  progress: number;
  /** The currently active stage, or null if queued. */
  currentStage: IndexingStage | null;
  /** Stages already finished, in pipeline order. */
  completedStages?: ReadonlyArray<IndexingStage>;
  hideHeaderActions?: boolean;
  hidePercent?: boolean;
  /** Accepted for backward-compat, never read. */
  estimatedRemainingSeconds?: number;
  /**
   * Drop the outer white card + heading row so the panel sits flush
   * inside a parent surface.
   */
  bare?: boolean;
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

function CheckMarkIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      fill="none"
      aria-hidden="true"
    >
      <rect width="24" height="24" rx="12" fill={GREEN_CHECK} />
      <path
        d="M17 8.66211L10.125 15.5371L7 12.4121"
        stroke="white"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Spinner() {
  return (
    <span
      className="block h-3 w-3 animate-spin rounded-full border-2 border-gray-200"
      style={{ borderTopColor: NAVY }}
      aria-hidden="true"
    />
  );
}

export function IndexingProgressPanel({
  criteria,
  videoDurationMs,
  progress,
  currentStage,
  completedStages = [],
  hideHeaderActions = false,
  hidePercent = false,
  bare = false,
}: Props) {
  const percent = clampPercent(progress);
  const completedSet = new Set<string>(completedStages);
  const showHeaderActions =
    !hideHeaderActions && criteria != null && videoDurationMs != null;

  const stepper = (
    <ol
      className="relative mx-auto flex w-full max-w-[520px] items-start"
      data-testid="indexing-stage-list"
      aria-label="쇼츠 생성 파이프라인"
    >
      {STAGES.map((stage, i) => {
        const isCompleted = completedSet.has(stage.id);
        const isActive = !isCompleted && currentStage === stage.id;
        const state: "completed" | "active" | "queued" = isCompleted
          ? "completed"
          : isActive
            ? "active"
            : "queued";
        return (
          <li
            key={stage.id}
            className="relative flex flex-1 flex-col items-center last:flex-none"
            data-testid={`indexing-stage-${stage.id}`}
            data-state={state}
          >
            {/* Connector to next stage. Starts at center of this
                circle (left: 50%) and ends at center of next (right:
                -50%). z-0 places it UNDER the circles so there's no
                visible gap at either end. */}
            {i < STAGES.length - 1 ? (
              <span
                aria-hidden="true"
                className="absolute top-4 z-0 h-[2px] -translate-y-1/2"
                style={{
                  left: "50%",
                  right: "-50%",
                  backgroundColor: isCompleted ? NAVY : QUEUED_GRAY,
                }}
              />
            ) : null}

            <span
              className={cn(
                "relative z-10 flex h-8 w-8 items-center justify-center rounded-full bg-white transition",
                !isCompleted &&
                  (isActive
                    ? "border-2"
                    : "border-2 border-gray-300"),
              )}
              style={isActive ? { borderColor: NAVY } : undefined}
            >
              {isCompleted ? (
                <CheckMarkIcon />
              ) : isActive ? (
                <Spinner />
              ) : (
                <span className="text-xs font-semibold text-gray-400">
                  {i + 1}
                </span>
              )}
            </span>

            <span
              className={cn(
                "mt-2 whitespace-nowrap text-[12px] font-medium tracking-[-0.3px]",
                isCompleted || isActive
                  ? "text-grayscale-800"
                  : "text-grayscale-500",
              )}
            >
              {stage.label}
            </span>
          </li>
        );
      })}
    </ol>
  );

  const body = (
    <>
      {!bare ? (
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-[20px] font-semibold tracking-[-0.5px] text-grayscale-800">
            AI 쇼츠 생성
          </h2>
          {showHeaderActions ? (
            <div className="flex items-center gap-[12px]">
              <span
                className="rounded-full bg-neutral-h-50 px-[12px] py-[6px] text-[12px] font-medium text-grayscale-500"
                data-testid="indexing-summary-chip"
              >
                {summaryChip(criteria!, videoDurationMs!)}
              </span>
              <Button variant="primary" size="sm" disabled>
                다음
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex w-full flex-col items-center gap-[24px] py-[12px]">
        {stepper}

        <div className="flex flex-col items-center gap-[6px]">
          {!hidePercent ? (
            <p
              className="text-[16px] font-semibold leading-[1.4] tracking-[-0.4px]"
              style={{ color: NAVY }}
              data-testid="indexing-progress-percent"
            >
              진행률 {percent}%
            </p>
          ) : null}
          <p
            className="text-[14px] font-medium tracking-[-0.35px] text-neutral-h-600"
            data-testid="indexing-progress-eta"
          >
            보통 30-90초 소요
          </p>
        </div>
      </div>
    </>
  );

  if (bare) {
    return (
      <div
        className="space-y-[20px] font-pretendard"
        data-testid="indexing-progress-bare"
      >
        {body}
      </div>
    );
  }

  return (
    <div className="space-y-[20px] font-pretendard">
      <div className="space-y-[40px] rounded-card bg-white p-[20px] shadow-card">
        {body}
      </div>
    </div>
  );
}
