// ============================================================================
// Inline-wizard Step 1 (옵션 설정) panel — props-driven, no router. Composes
// the inline selectors + range slider + breadcrumb. Parent owns criteria
// state (so back-nav from product step preserves it).
//
// Distinct from the legacy ``WizardStepCriteria.tsx`` which is route-driven
// and pushes URL params on submit. That route stays alive for backward
// compatibility — this panel does NOT subsume it.
// ============================================================================

// figma: 1713-288216  (cache: .figma-cache/1713-288216_phase2_wizard-criteria.api.json)
// node-name: Wizard Criteria Step 1  · spec: section-label=16/600 grayscale-800, card padding=20, inner gap=60, header pb=20

"use client";

import { useMemo } from "react";

import { Button } from "@/components/ui/figma-index";
import { useTopHeaderLeftActions } from "@/components/layout/TopHeaderActionsContext";
import type { ProductDistribution } from "@/lib/types/shorts-auto-product-wizard";

import { InlineCountSelector } from "./InlineCountSelector";
import { InlineDistributionToggle } from "./InlineDistributionToggle";
import { InlineLengthSelector } from "./InlineLengthSelector";
import { InlineWizardBreadcrumb } from "./InlineWizardBreadcrumb";
import { VideoSegmentRangeSlider } from "./VideoSegmentRangeSlider";

/**
 * Subset of ``ScanOrderCreateRequest`` that the user actually sets in the
 * inline flow. ``language`` is hardcoded to "ko" at submit time;
 * ``intent`` is always "commit"; ``catalog_entry_id`` is added at the
 * product step. Defined here (not in lib/types) because it's an
 * inline-flow-specific shape, not a backend contract.
 */
export interface WizardCriteriaDraft {
  length_seconds: number;
  requested_count: number;
  time_range_start_ms: number | null;
  time_range_end_ms: number | null;
  product_distribution: ProductDistribution;
}

export const DEFAULT_CRITERIA: WizardCriteriaDraft = {
  length_seconds: 60,
  requested_count: 5,
  time_range_start_ms: null,
  time_range_end_ms: null,
  product_distribution: "single",
};

interface Props {
  videoId: string;
  videoDurationMs: number;
  /**
   * Optional scene boundaries (ms) the range slider snaps to when
   * dragged within its grace zone. Forwarded as-is to the slider.
   * Empty / undefined disables snap (free dragging).
   */
  snapTargetsMs?: number[];
  criteria: WizardCriteriaDraft;
  onCriteriaChange: (next: WizardCriteriaDraft) => void;
  onNext: () => void;
}

const AGGREGATE_CAP_SECONDS = 1800;

export function InlineWizardCriteriaPanel({
  videoDurationMs,
  snapTargetsMs,
  criteria,
  onCriteriaChange,
  onNext,
}: Props) {
  const aggregateSeconds = criteria.length_seconds * criteria.requested_count;
  const exceedsAggregateCap = aggregateSeconds > AGGREGATE_CAP_SECONDS;

  // Effective range for the smart-count suggestion: when the user hasn't
  // constrained the range, fall back to the whole video. This matches
  // the slider's display behavior (handles at extremes).
  const effectiveRangeMs =
    criteria.time_range_start_ms != null && criteria.time_range_end_ms != null
      ? criteria.time_range_end_ms - criteria.time_range_start_ms
      : videoDurationMs;

  const update = <K extends keyof WizardCriteriaDraft>(
    key: K,
    value: WizardCriteriaDraft[K],
  ) => {
    onCriteriaChange({ ...criteria, [key]: value });
  };

  // Step indicator lives in the global TopHeader (GNB) per Figma 1602:36766.
  // The wizard body intentionally omits its own breadcrumb header.
  const headerSlot = useMemo(
    () => <InlineWizardBreadcrumb currentStep={1} />,
    [],
  );
  useTopHeaderLeftActions(headerSlot);

  return (
    <div className="space-y-[20px] font-pretendard">
      <div className="rounded-card bg-white p-[20px] shadow-card">
        <div className="flex items-center justify-between gap-4 pb-[20px]">
          <h2 className="text-[20px] font-semibold tracking-[-0.5px] text-grayscale-800">
            옵션 설정
          </h2>
          <Button
            variant="primary"
            size="sm"
            onClick={onNext}
            disabled={exceedsAggregateCap}
            data-testid="inline-criteria-next"
          >
            다음
          </Button>
        </div>

        <div className="flex flex-col gap-[60px]">
          <InlineDistributionToggle
            value={criteria.product_distribution}
            onChange={(v) => update("product_distribution", v)}
          />

          <div className="space-y-[12px]">
            <label className="block text-[16px] font-semibold text-grayscale-800">
              영상 구간 설정
            </label>
            <VideoSegmentRangeSlider
              durationMs={videoDurationMs}
              snapTargetsMs={snapTargetsMs}
              startMs={criteria.time_range_start_ms}
              endMs={criteria.time_range_end_ms}
              onChange={({ startMs, endMs }) =>
                onCriteriaChange({
                  ...criteria,
                  time_range_start_ms: startMs,
                  time_range_end_ms: endMs,
                })
              }
            />
          </div>

          <InlineLengthSelector
            value={criteria.length_seconds}
            onChange={(v) => update("length_seconds", v)}
          />

          <InlineCountSelector
            value={criteria.requested_count}
            onChange={(v) => update("requested_count", v)}
            rangeMs={effectiveRangeMs}
            lengthSeconds={criteria.length_seconds}
          />
        </div>

        {exceedsAggregateCap ? (
          <p
            className="mt-[20px] rounded-[8px] bg-amber-h-50 p-[12px] text-[13px] font-medium text-amber-h-500"
            data-testid="inline-aggregate-cap-warning"
          >
            총 출력 길이 한도(30분) 초과: {criteria.requested_count}개 ×{" "}
            {criteria.length_seconds}초 = {aggregateSeconds}초. 개수 또는
            길이를 줄여주세요.
          </p>
        ) : null}
      </div>
    </div>
  );
}
