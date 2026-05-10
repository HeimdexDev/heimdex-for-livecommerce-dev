// ============================================================================
// Inline-wizard Step 2 (상품 선택) panel — props-driven product selection.
// Same enumeration polling logic as the legacy ``WizardStepSelectProduct``
// (intentionally duplicated; the legacy file stays alive for the route-based
// flow until Phase D3 deletion).
//
// PR 3 of the multi-product wizard plan: multi-select UI. Backend (PR 2)
// accepts ``catalog_entry_ids: string[]`` with validation
// ``1 <= len <= requested_count``. Cap is enforced client-side: clicking
// a non-selected card at the cap is silently ignored (the K/N counter
// makes the cap visible). See
// ``.claude/plans/wizard-multi-product-select.md`` (PR 3 of 3).
// ============================================================================

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  WizardBudgetExceededError,
  WizardFeatureDisabledError,
  WizardRateLimitError,
  WizardValidationError,
  createScanOrder,
  getProductCatalog,
  triggerEnumeration,
} from "@/lib/api/shorts-auto-product-wizard";
import { useAuth } from "@/lib/auth";
import { formatVideoTimestampHMS } from "@/lib/timeline";
import type { CatalogProductSummary } from "@/lib/types/shorts-auto-product-wizard";
import { cn } from "@/lib/utils";

import { InlineWizardBreadcrumb } from "./InlineWizardBreadcrumb";
import type { WizardCriteriaDraft } from "./InlineWizardCriteriaPanel";
import { normalizeTimeRangeForSubmit } from "./VideoSegmentRangeSlider";

const POLL_INTERVAL_MS = 5_000;
const POLL_TIMEOUT_MS = 180_000;

interface Props {
  videoId: string;
  videoDurationMs: number;
  criteria: WizardCriteriaDraft;
  onSubmitOrder: (parentJobId: string) => void;
  onBack: () => void;
}

type PollState = "enumerating" | "ready" | "no_products" | "error";

function distributionLabel(value: WizardCriteriaDraft["product_distribution"]) {
  return value === "single" ? "상품별 쇼츠" : "통합 쇼츠";
}

function rangeLabel(criteria: WizardCriteriaDraft, durationMs: number): string {
  const start = criteria.time_range_start_ms ?? 0;
  const end = criteria.time_range_end_ms ?? durationMs;
  return `${formatVideoTimestampHMS(start)} - ${formatVideoTimestampHMS(end)}`;
}

function summaryChip(
  criteria: WizardCriteriaDraft,
  durationMs: number,
): string {
  return [
    distributionLabel(criteria.product_distribution),
    rangeLabel(criteria, durationMs),
    `${criteria.length_seconds}초 길이`,
    `${criteria.requested_count}개 생성`,
  ].join(" · ");
}

export function InlineWizardProductPanel({
  videoId,
  videoDurationMs,
  criteria,
  onSubmitOrder,
  onBack,
}: Props) {
  const { getAccessToken } = useAuth();

  const [entries, setEntries] = useState<CatalogProductSummary[]>([]);
  const [pollState, setPollState] = useState<PollState>("enumerating");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // PR 3: multi-select state. Set membership = card selected. Clicking
  // an unselected card when ``size === requested_count`` is silently
  // ignored (the K/N counter is the visible affordance).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [submitting, setSubmitting] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const startedAtRef = useRef<number>(Date.now());

  // Effect duplicates legacy polling logic verbatim. Once the legacy
  // page is deleted (Phase D3), the polling loop has only one home.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (cancelled) return;
      try {
        const resp = await getProductCatalog(videoId, getAccessToken);
        if (cancelled) return;
        if (resp.products.length > 0) {
          setEntries(resp.products);
          setPollState("ready");
          return;
        }
        if (resp.scan_status === "failed") {
          setErrorMessage("이전 스캔이 실패했어요. 다시 시도해 주세요.");
          setPollState("error");
          return;
        }
        if (resp.scan_status === "complete") {
          setPollState("no_products");
          return;
        }
        if (Date.now() - startedAtRef.current >= POLL_TIMEOUT_MS) {
          setPollState("no_products");
          return;
        }
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } catch (err) {
        if (cancelled) return;
        setErrorMessage(
          err instanceof Error ? err.message : "카탈로그 로드 실패",
        );
        setPollState("error");
      }
    };

    const start = async () => {
      try {
        await triggerEnumeration(
          videoId,
          { duration_preset_sec: 60 },
          getAccessToken,
        );
      } catch (err) {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.warn(
          "[inline-wizard] triggerEnumeration failed; will still poll",
          err,
        );
      }
      void poll();
    };

    void start();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, getAccessToken, retryCount]);

  const handleSubmit = useCallback(async () => {
    if (selectedIds.size === 0) return;
    setErrorMessage(null);
    setSubmitting(true);
    try {
      // PR 3: submit the new ``catalog_entry_ids`` list. Sorted
      // client-side so it matches the server's canonical hash form
      // (PR 2's settings_hash sorts the list before hashing); two
      // submissions with the same set in different click orders
      // dedupe correctly within the 60s idempotency window.
      // Belt-and-braces XOR normalization: the slider already emits
      // both-or-neither, but this guards against any future criteria
      // mutation path that bypasses the slider.
      const range = normalizeTimeRangeForSubmit(
        criteria.time_range_start_ms,
        criteria.time_range_end_ms,
        videoDurationMs,
      );
      const response = await createScanOrder(
        videoId,
        {
          length_seconds: criteria.length_seconds,
          requested_count: criteria.requested_count,
          time_range_start_ms: range.startMs,
          time_range_end_ms: range.endMs,
          product_distribution: criteria.product_distribution,
          language: "ko", // Hardcoded — inline UI drops the toggle (Decision #1 surroundings)
          intent: "commit",
          catalog_entry_ids: Array.from(selectedIds).sort(),
        },
        getAccessToken,
      );
      onSubmitOrder(response.parent_job_id);
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
        setErrorMessage(err instanceof Error ? err.message : "Unknown error");
      }
      setSubmitting(false);
    }
  }, [criteria, selectedIds, videoId, videoDurationMs, getAccessToken, onSubmitOrder]);

  const handleRetry = () => {
    startedAtRef.current = Date.now();
    setEntries([]);
    setSelectedIds(new Set());
    setErrorMessage(null);
    setPollState("enumerating");
    setRetryCount((n) => n + 1);
  };

  const selectedCount = selectedIds.size;
  const cap = criteria.requested_count;
  const atCap = selectedCount >= cap;

  // PR 3: card click toggles membership. At-cap clicks on unselected
  // cards are silently ignored (the K/N counter is the visible cue).
  // De-selecting is always allowed regardless of cap.
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      if (prev.has(id)) {
        const next = new Set(prev);
        next.delete(id);
        return next;
      }
      if (prev.size >= cap) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between gap-4">
        <button
          type="button"
          onClick={onBack}
          className="text-sm text-gray-500 hover:text-gray-700"
          data-testid="inline-product-back"
        >
          &lt; 뒤로가기
        </button>
        <InlineWizardBreadcrumb currentStep={2} />
      </header>

      <div className="space-y-4 rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              상품 선택{" "}
              <span className="text-sm font-normal text-gray-500">
                {entries.length}개 중 {selectedCount}/{cap}개 선택
              </span>
            </h2>
          </div>
          <div className="flex items-center gap-3">
            <span
              className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600"
              data-testid="inline-product-summary-chip"
            >
              {summaryChip(criteria, videoDurationMs)}
            </span>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={
                selectedIds.size === 0 ||
                submitting ||
                pollState !== "ready"
              }
              className="rounded-md bg-gray-900 px-4 py-1.5 text-sm font-medium text-white transition hover:bg-gray-800 disabled:bg-gray-300 disabled:text-gray-500"
              data-testid="inline-product-next"
            >
              {submitting ? "생성 중..." : "다음"}
            </button>
          </div>
        </div>

        {pollState === "ready" ? (
          <p className="rounded-md bg-gray-50 p-3 text-center text-xs text-gray-600">
            선택한 상품을 모두 포함한 쇼츠 {criteria.requested_count}개를
            생성합니다.
          </p>
        ) : null}

        {pollState === "enumerating" ? (
          <div
            className="space-y-3 rounded-md border border-gray-100 bg-white p-6 text-center"
            data-testid="inline-product-loading"
          >
            <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-gray-900 border-t-transparent" />
            <p className="text-sm text-gray-700">
              영상에서 제품을 찾고 있어요... (보통 30–90초 소요)
            </p>
            <p className="text-xs text-gray-500">
              이미 스캔한 영상이라면 즉시 결과가 표시됩니다.
            </p>
          </div>
        ) : null}

        {pollState === "no_products" ? (
          <div
            className="space-y-2 rounded-md border border-amber-200 bg-amber-50 p-6"
            data-testid="inline-product-no-products"
          >
            <h3 className="text-sm font-semibold text-amber-900">
              제품을 찾을 수 없어요
            </h3>
            <p className="text-xs text-amber-800">
              이 영상에서 자동으로 인식할 수 있는 제품이 없습니다. 다른
              영상을 선택하거나, 영상에 제품이 잘 보이는 시간 구간을
              지정해 보세요.
            </p>
          </div>
        ) : null}

        {pollState === "error" ? (
          <div
            className="space-y-3 rounded-md border border-red-200 bg-red-50 p-6"
            data-testid="inline-product-error"
          >
            <h3 className="text-sm font-semibold text-red-900">
              제품 스캔에 실패했어요
            </h3>
            <p className="text-xs text-red-800">
              {errorMessage ?? "잠시 후 다시 시도해 주세요."}
            </p>
            <button
              type="button"
              onClick={handleRetry}
              className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700"
              data-testid="inline-product-retry"
            >
              다시 시도
            </button>
          </div>
        ) : null}

        {pollState === "ready" && entries.length > 0 ? (
          <div
            className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4"
            data-testid="inline-product-grid"
          >
            {entries.map((entry) => {
              const isSelected = selectedIds.has(entry.catalog_entry_id);
              const disabled = !isSelected && atCap;
              return (
                <button
                  key={entry.catalog_entry_id}
                  type="button"
                  onClick={() => toggleSelect(entry.catalog_entry_id)}
                  disabled={disabled}
                  className={cn(
                    "group relative overflow-hidden rounded-lg border bg-white text-left transition",
                    isSelected
                      ? "border-gray-900 ring-2 ring-gray-900"
                      : "border-gray-200 hover:border-gray-400",
                    disabled && "cursor-not-allowed opacity-50",
                  )}
                  data-testid="inline-product-card"
                  data-selected={isSelected}
                  data-catalog-entry-id={entry.catalog_entry_id}
                >
                  <div className="aspect-square overflow-hidden bg-gray-100">
                    {entry.canonical_crop_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={entry.canonical_crop_url}
                        alt={entry.label}
                        className="h-full w-full object-cover transition group-hover:scale-105"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-xs text-gray-400">
                        이미지 없음
                      </div>
                    )}
                    <span
                      className={cn(
                        "absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-md border-2 transition",
                        isSelected
                          ? "border-gray-900 bg-gray-900 text-white"
                          : "border-gray-300 bg-white/80 text-transparent",
                      )}
                      aria-hidden="true"
                      data-testid="inline-product-checkmark"
                    >
                      ✓
                    </span>
                  </div>
                  <div className="p-3">
                    <p
                      className="line-clamp-1 text-sm font-medium text-gray-900"
                      title={entry.label}
                    >
                      {entry.label}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
        ) : null}

        {pollState === "ready" && errorMessage ? (
          <p
            className="rounded-md bg-red-50 p-3 text-sm text-red-700"
            data-testid="inline-product-submit-error"
          >
            {errorMessage}
          </p>
        ) : null}
      </div>
    </div>
  );
}
