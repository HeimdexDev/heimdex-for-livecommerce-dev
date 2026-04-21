// Map backend `skipped_reason` enum values → Korean user copy.
// Pure function. The test at __tests__/skip-reason-copy.test.ts fails
// when a new reason is added to AutoSelectSkippedReason without a copy
// entry — guards against silent "unknown reason" UX.

import type { AutoSelectSkippedReason } from "@/lib/types";
import type { ScoringModeRequest } from "@/lib/types";

const BASE_COPY: Record<AutoSelectSkippedReason, string> = {
  video_too_short: "이 영상은 너무 짧아 자동 쇼츠를 만들 수 없습니다 (최소 5분 이상 필요).",
  no_candidate_scenes_after_filter: "선택한 조건에 맞는 장면이 없습니다. 다른 모드를 시도해 보세요.",
  no_scenes_passed_eligibility: "기준을 통과한 장면이 없습니다. 조건을 완화해 보세요.",
  no_clips_met_min_duration: "쇼츠 최소 길이를 만족하는 장면이 부족합니다. 다른 영상을 선택해 주세요.",
};

const PRODUCT_MODE_OVERRIDE: Partial<Record<AutoSelectSkippedReason, string>> = {
  no_candidate_scenes_after_filter: "상품이 단독으로 등장하는 장면을 찾지 못했습니다. 혼합 모드로 시도해 보세요.",
};

const HUMAN_MODE_OVERRIDE: Partial<Record<AutoSelectSkippedReason, string>> = {
  no_candidate_scenes_after_filter: "선택한 인물이 등장하는 장면이 부족합니다. 다른 인물을 선택하거나 혼합 모드로 시도해 보세요.",
};

/**
 * @param reason value emitted by the backend in `AutoSelectResponse.skipped_reason`
 * @param mode the request mode — lets us surface mode-specific hints
 * @returns Korean copy suitable for rendering in an empty-state card
 */
export function skipReasonCopy(
  reason: string | null | undefined,
  mode?: ScoringModeRequest,
): string {
  if (!reason) {
    return "조건에 맞는 쇼츠를 만들지 못했습니다.";
  }
  if (mode === "product") {
    const override = PRODUCT_MODE_OVERRIDE[reason as AutoSelectSkippedReason];
    if (override) return override;
  }
  if (mode === "human") {
    const override = HUMAN_MODE_OVERRIDE[reason as AutoSelectSkippedReason];
    if (override) return override;
  }
  return BASE_COPY[reason as AutoSelectSkippedReason] ?? "쇼츠 생성 조건을 만족하지 못했습니다.";
}

export { BASE_COPY as __SKIP_REASON_BASE_COPY_FOR_TESTS };
