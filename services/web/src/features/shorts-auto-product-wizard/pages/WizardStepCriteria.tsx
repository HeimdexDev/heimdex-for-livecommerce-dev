// ============================================================================
// Step 2 — 생성 기준 설정 (criteria form)
//
// The headline screen from the wizard mockup. Five inputs:
//   * length_seconds (LengthSelector — 15/30/60/90/120 + custom)
//   * time_range_start_ms / time_range_end_ms (mm:ss text inputs;
//     drag-handle slider deferred to follow-up PR per plan §8.3)
//   * requested_count (CountSelector — 5/10/15/20 + custom)
//   * product_distribution (개별 / 여러)
//   * language (한국어 / 영어)
//
// On submit: POST /api/shorts/auto/scan-orders/videos/{videoId} → on success
// route to step 4 with the parent_job_id; on 422 surface the message;
// on 402 / 429 surface friendly copy.
// ============================================================================

"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/lib/auth";
import {
  WizardBudgetExceededError,
  WizardFeatureDisabledError,
  WizardRateLimitError,
  WizardValidationError,
  createScanOrder,
} from "@/lib/api/shorts-auto-product-wizard";
import type {
  Language,
  ProductDistribution,
} from "@/lib/types/shorts-auto-product-wizard";

import { CountSelector } from "../components/CountSelector";
import { LanguageToggle } from "../components/LanguageToggle";
import { LengthSelector } from "../components/LengthSelector";
import { ProductDistributionToggle } from "../components/ProductDistributionToggle";
import { WizardLayout } from "../components/WizardLayout";

interface Props {
  videoId: string;
}

/**
 * Convert "mm:ss" or "" to milliseconds (or null when blank).
 * Tolerant — bad input parses to null and the field shows raw text.
 */
function parseMmSsToMs(raw: string): number | null {
  if (!raw.trim()) return null;
  const match = raw.match(/^(\d+):(\d{1,2})$/);
  if (!match) return null;
  const minutes = Number.parseInt(match[1] || "0", 10);
  const seconds = Number.parseInt(match[2] || "0", 10);
  if (Number.isNaN(minutes) || Number.isNaN(seconds)) return null;
  if (seconds > 59) return null;
  return (minutes * 60 + seconds) * 1000;
}

export function WizardStepCriteria({ videoId }: Props) {
  const router = useRouter();
  const { getAccessToken } = useAuth();

  // Form state — defaults match the most-common preset choices.
  const [lengthSeconds, setLengthSeconds] = useState<number>(60);
  const [requestedCount, setRequestedCount] = useState<number>(5);
  const [rangeStartRaw, setRangeStartRaw] = useState<string>("");
  const [rangeEndRaw, setRangeEndRaw] = useState<string>("");
  const [distribution, setDistribution] =
    useState<ProductDistribution>("single");
  const [language, setLanguage] = useState<Language>("ko");

  // Submission state
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Inline aggregate-cap warning (server enforces; this is an early hint).
  const aggregateSeconds = lengthSeconds * requestedCount;
  const exceedsAggregateCap = aggregateSeconds > 1800;

  const handleSubmit = async () => {
    setErrorMessage(null);
    setSubmitting(true);
    try {
      const response = await createScanOrder(
        videoId,
        {
          length_seconds: lengthSeconds,
          requested_count: requestedCount,
          time_range_start_ms: parseMmSsToMs(rangeStartRaw),
          time_range_end_ms: parseMmSsToMs(rangeEndRaw),
          product_distribution: distribution,
          language,
          intent: "commit", // Phase 4: skip preview, go straight to commit
        },
        getAccessToken,
      );
      router.push(
        `/export/shorts/auto/wizard/${encodeURIComponent(videoId)}/result/${encodeURIComponent(response.parent_job_id)}`,
      );
    } catch (err) {
      if (err instanceof WizardValidationError) {
        setErrorMessage(`입력 오류: ${err.message}`);
      } else if (err instanceof WizardBudgetExceededError) {
        setErrorMessage(`일일 비용 한도 초과: ${err.message}`);
      } else if (err instanceof WizardRateLimitError) {
        setErrorMessage(`동시 실행 한도 초과: ${err.message}`);
      } else if (err instanceof WizardFeatureDisabledError) {
        setErrorMessage("이 조직에는 마법사 기능이 활성화되지 않았습니다.");
      } else {
        setErrorMessage(
          err instanceof Error ? err.message : "Unknown error",
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit = !submitting && !exceedsAggregateCap;

  return (
    <WizardLayout
      currentStep={2}
      heading="생성 기준을 선택하고, '다음'버튼을 클릭하세요"
      next={{
        label: submitting ? "생성 중..." : "다음 >",
        onClick: handleSubmit,
        disabled: !canSubmit,
      }}
      backHref="/export/shorts/auto/wizard"
    >
      <div className="space-y-6 rounded-lg border border-gray-200 bg-white p-6">
        <LengthSelector value={lengthSeconds} onChange={setLengthSeconds} />

        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700">
            주로 처리할 동영상 구간
          </label>
          <div className="flex items-center gap-2 text-sm">
            <input
              type="text"
              placeholder="00:00"
              value={rangeStartRaw}
              onChange={(e) => setRangeStartRaw(e.target.value)}
              className="w-24 rounded-md border border-gray-300 px-2 py-1.5"
              data-testid="range-start-input"
            />
            <span className="text-gray-500">~</span>
            <input
              type="text"
              placeholder="mm:ss"
              value={rangeEndRaw}
              onChange={(e) => setRangeEndRaw(e.target.value)}
              className="w-24 rounded-md border border-gray-300 px-2 py-1.5"
              data-testid="range-end-input"
            />
            <span className="text-xs text-gray-500">
              비워두면 동영상 전체에서 선택
            </span>
          </div>
          <p className="text-xs text-gray-500">
            드래그 가능한 슬라이더는 다음 PR에서 추가됩니다.
          </p>
        </div>

        <CountSelector value={requestedCount} onChange={setRequestedCount} />

        <ProductDistributionToggle
          value={distribution}
          onChange={setDistribution}
        />

        <LanguageToggle value={language} onChange={setLanguage} />

        {exceedsAggregateCap ? (
          <p
            className="rounded-md bg-amber-50 p-3 text-sm text-amber-800"
            data-testid="aggregate-cap-warning"
          >
            총 출력 길이 한도(30분) 초과: {requestedCount}개 ×{" "}
            {lengthSeconds}초 = {aggregateSeconds}초. 개수 또는 길이를
            줄여주세요.
          </p>
        ) : null}

        {errorMessage ? (
          <p
            className="rounded-md bg-red-50 p-3 text-sm text-red-700"
            data-testid="error-message"
          >
            {errorMessage}
          </p>
        ) : null}
      </div>
    </WizardLayout>
  );
}
