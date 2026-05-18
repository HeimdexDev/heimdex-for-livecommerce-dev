// figma: 1713:288149  (cache: .figma-cache/1713-288149_phase2_wizard-product-single.api.json)
// figma: 1713:288182  (cache: .figma-cache/1713-288182_phase2_wizard-product-multi.api.json)
// node-name: 2-6.c/d AI 쇼츠 생성 (상품 선택)
//   spec: card radius=10(rounded-card) shadow=shadow-card padL/R/T/B=20(p-5) gap=20(space-y-5)
//   grid: max-w=7xl cols 2/3/4(sm/lg) gap=20(gap-5)  // Q3 — 5-col 미채택, 4-col 유지
//   checkbox: 24×24(h-6 w-6) radius=6(rounded-md) top/right=8(top-2 right-2) check icon 16(h-4 w-4)
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

import { Check } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, Snackbar } from "@/components/ui/figma-index";
import { useTopHeaderLeftActions } from "@/components/layout/TopHeaderActionsContext";
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

import {
  IndexingProgressPanel,
  type IndexingStage,
} from "./IndexingProgressPanel";
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
  /**
   * How long (ms) to keep the 100% completion screen on after the
   * catalog poll first returns products, before flipping to the
   * product grid. Defaults to 3000 — the live UX wants the operator to
   * see the "all stages checked" moment briefly. Tests override with 0
   * so assertions land synchronously after the mock resolves.
   */
  completionHoldMs?: number;
}

type PollState = "enumerating" | "ready" | "no_products" | "timeout" | "error";

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
  completionHoldMs = 3000,
}: Props) {
  void onBack; // back affordance moved to TopHeader chevron (2026-05-18)
  const { getAccessToken } = useAuth();

  const [entries, setEntries] = useState<CatalogProductSummary[]>([]);
  const [pollState, setPollState] = useState<PollState>("enumerating");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // 2026-05-18 — fake-it-til-you-make-it stage display. Enumeration is
  // the only backend work happening on step 2-1, but the operator
  // expects the same 4-stage progression they'll see on step 3. We
  // track elapsed time + a "post-completion" timestamp so the UI can
  // advance through the stages and hold at 100% for 3s before flipping
  // to the product grid.
  const [stageTick, setStageTick] = useState(0);
  const [completedAt, setCompletedAt] = useState<number | null>(null);
  // PR 3: multi-select state. Set membership = card selected. Clicking
  // an unselected card when ``size === requested_count`` is silently
  // ignored (the K/N counter is the visible affordance).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [submitting, setSubmitting] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  // multi-mode cap toast — fired when an at-cap user tries to add another
  // card. Auto-dismisses after 2.5s so the snackbar doesn't stack.
  const [showCapSnackbar, setShowCapSnackbar] = useState(false);
  const startedAtRef = useRef<number>(Date.now());
  const capSnackbarTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

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
          // Cache the products + mark the completion moment. The grid
          // doesn't render yet — the post-completion timer below holds
          // pollState at "enumerating" for ~3s so the progress card
          // shows all four stages checked + 100% before flipping.
          setEntries(resp.products);
          setCompletedAt(Date.now());
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
          setPollState("timeout");
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

  // Drive the stage display tick. Re-renders every 250ms while the
  // panel is enumerating so the percentage + stage advance smoothly
  // off the elapsed time. Stops once we leave the enumerating state.
  useEffect(() => {
    if (pollState !== "enumerating") return;
    const id = setInterval(() => setStageTick((t) => t + 1), 250);
    return () => clearInterval(id);
  }, [pollState]);

  // Hold the 100% display for ``completionHoldMs`` after the catalog
  // poll first succeeds, then flip to the product grid. Tests pass 0
  // so the assertion that follows the mock resolution lands without
  // a setTimeout boundary.
  useEffect(() => {
    if (completedAt == null) return;
    const id = setTimeout(() => setPollState("ready"), completionHoldMs);
    return () => clearTimeout(id);
  }, [completedAt, completionHoldMs]);

  // Derive the simulated progress / stage from elapsed time. Each
  // stage gets ~15s of headroom (60s total estimate) before the next
  // one lights up. After ``completedAt`` lands all four stages are
  // marked done and the percent jumps to 100.
  const STAGE_ORDER: ReadonlyArray<IndexingStage> = [
    "enumerating",
    "tracking",
    "assembling",
    "rendering",
  ];
  const STAGE_DURATION_MS = 15_000;
  void stageTick; // tick is only used to force the re-render
  const elapsedMs = Date.now() - startedAtRef.current;
  let stageIdx: number;
  let progressPct: number;
  if (completedAt != null) {
    stageIdx = STAGE_ORDER.length;
    progressPct = 100;
  } else {
    stageIdx = Math.min(
      STAGE_ORDER.length - 1,
      Math.floor(elapsedMs / STAGE_DURATION_MS),
    );
    // Cap at 95% so the bar visibly jumps to 100 when the catalog
    // actually finishes — otherwise the simulation can hit 100 before
    // the backend confirms and the "completion" moment loses impact.
    progressPct = Math.min(
      95,
      Math.round((elapsedMs / (STAGE_DURATION_MS * STAGE_ORDER.length)) * 100),
    );
  }
  const simulatedCurrentStage: IndexingStage | null =
    stageIdx < STAGE_ORDER.length ? STAGE_ORDER[stageIdx] : null;
  const simulatedCompletedStages = STAGE_ORDER.slice(0, stageIdx);

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

  // Card click toggles membership. At-cap clicks on unselected cards are
  // silently ignored for single-mode (the K/N counter is the visible cue),
  // but multi-mode fires a Snackbar per Figma 1713:288182 — the cap is
  // the user-visible affordance there. De-selecting is always allowed.
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      if (prev.has(id)) {
        const next = new Set(prev);
        next.delete(id);
        return next;
      }
      if (prev.size >= cap) {
        if (criteria.product_distribution === "multi") {
          if (capSnackbarTimerRef.current) {
            clearTimeout(capSnackbarTimerRef.current);
          }
          setShowCapSnackbar(true);
          capSnackbarTimerRef.current = setTimeout(
            () => setShowCapSnackbar(false),
            2500,
          );
        }
        return prev;
      }
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  };

  useEffect(
    () => () => {
      if (capSnackbarTimerRef.current) clearTimeout(capSnackbarTimerRef.current);
    },
    [],
  );

  // Entry toast (figma 1713:288207) — fires once per panel mount in
  // multi mode so users learn the cap rule before they hit it. Auto-
  // dismisses after 4s; reuses the cap snackbar slot so only one is
  // ever on screen at a time.
  const introShownRef = useRef(false);
  useEffect(() => {
    if (introShownRef.current) return;
    if (criteria.product_distribution !== "multi") return;
    if (pollState !== "ready") return;
    introShownRef.current = true;
    setShowCapSnackbar(true);
    if (capSnackbarTimerRef.current) clearTimeout(capSnackbarTimerRef.current);
    capSnackbarTimerRef.current = setTimeout(
      () => setShowCapSnackbar(false),
      4000,
    );
  }, [criteria.product_distribution, pollState]);

  const isMulti = criteria.product_distribution === "multi";
  const guidanceCopy = isMulti
    ? `선택한 상품마다 하나씩, 별도의 쇼츠 ${criteria.requested_count}개를 생성합니다. 상품은 최대 ${cap}개까지 선택 가능합니다.`
    : `선택한 상품을 모두 포함한 쇼츠 ${criteria.requested_count}개를 생성합니다.`;

  // Step indicator lives in the global TopHeader (GNB) per Figma 1602:36766.
  const headerSlot = useMemo(
    () => <InlineWizardBreadcrumb currentStep={2} />,
    [],
  );
  useTopHeaderLeftActions(headerSlot);

  return (
    <div className="space-y-[20px] font-pretendard">
      {/* 뒤로가기 header was removed 2026-05-18 — TopHeader's back chevron
          already covers the navigation, and the nested header row
          created a visible extra-wrapper effect inside the card. The
          ``onBack`` callback is preserved for callers that still want
          to surface it elsewhere. */}
      <div className="space-y-5 rounded-card bg-white p-5 shadow-card">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-[18px] font-semibold tracking-[-0.45px] text-grayscale-800">
            상품 선택{" "}
            <span className="ml-[4px] text-[14px] font-medium text-grayscale-500">
              {entries.length}개 중 {selectedCount}개 선택
            </span>
          </h2>
          <div className="flex items-center gap-[12px]">
            <span
              className="rounded-full bg-neutral-h-50 px-[12px] py-[6px] text-[12px] font-medium text-grayscale-500"
              data-testid="inline-product-summary-chip"
            >
              {summaryChip(criteria, videoDurationMs)}
            </span>
            <Button
              variant="primary"
              size="sm"
              onClick={handleSubmit}
              disabled={
                selectedIds.size === 0 ||
                submitting ||
                pollState !== "ready"
              }
              data-testid="inline-product-next"
            >
              {submitting ? "생성 중..." : "다음"}
            </Button>
          </div>
        </div>

        {pollState === "ready" ? (
          <p className="rounded-[8px] bg-neutral-h-50 px-[12px] py-[10px] text-center text-[12px] font-medium text-heimdex-navy-500">
            {guidanceCopy}
          </p>
        ) : null}

        {pollState === "enumerating" ? (
          // 2026-05-18 — render the 4-stage indexing panel in ``bare``
          // mode so it inherits the outer card instead of drawing its
          // own. Stage + percent are simulated client-side off elapsed
          // time; once the catalog poll succeeds we hold at 100% with
          // every stage checked for 3s before pollState flips to
          // "ready" (handled by the completedAt timer above).
          <div data-testid="inline-product-loading">
            <IndexingProgressPanel
              progress={progressPct / 100}
              currentStage={simulatedCurrentStage}
              completedStages={simulatedCompletedStages}
              hideHeaderActions
              bare
            />
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

        {pollState === "timeout" ? (
          <div
            className="space-y-3 rounded-md border border-amber-200 bg-amber-50 p-6"
            data-testid="inline-product-timeout"
          >
            <h3 className="text-sm font-semibold text-amber-900">
              제품 스캔이 아직 끝나지 않았어요
            </h3>
            <p className="text-xs text-amber-800">
              처리 시간이 예상보다 길어지고 있습니다. 스캔은 계속 진행될 수
              있으니 잠시 후 다시 확인해 주세요.
            </p>
            <button
              type="button"
              onClick={handleRetry}
              className="rounded-md bg-amber-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-800"
              data-testid="inline-product-timeout-retry"
            >
              다시 확인
            </button>
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
            className="mx-auto grid max-w-7xl grid-cols-2 gap-5 sm:grid-cols-3 lg:grid-cols-4"
            data-testid="inline-product-grid"
          >
            {entries.map((entry) => {
              const isSelected = selectedIds.has(entry.catalog_entry_id);
              const blockedByCap = !isSelected && atCap;
              return (
                <button
                  key={entry.catalog_entry_id}
                  type="button"
                  onClick={() => toggleSelect(entry.catalog_entry_id)}
                  className={cn(
                    "group relative overflow-hidden rounded-card bg-white text-left transition",
                    isSelected
                      ? "border-2 border-heimdex-navy-500"
                      : "border border-grayscale-100 hover:border-heimdex-navy-400",
                    // Cap-blocked cards stay clickable in multi-mode so the
                    // Snackbar can fire; single-mode swallows the click via
                    // toggleSelect's no-op return path.
                    blockedByCap && !isMulti && "opacity-60",
                  )}
                  data-testid="inline-product-card"
                  data-selected={isSelected}
                  data-catalog-entry-id={entry.catalog_entry_id}
                >
                  <div className="aspect-square overflow-hidden bg-neutral-h-50">
                    {entry.canonical_crop_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={entry.canonical_crop_url}
                        alt={entry.label}
                        className="h-full w-full object-cover transition group-hover:scale-105"
                        loading="lazy"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-[12px] text-grayscale-500">
                        이미지 없음
                      </div>
                    )}
                    <span
                      className={cn(
                        "absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-md transition",
                        isSelected
                          ? "bg-heimdex-navy-500 text-white"
                          : "border-2 border-grayscale-100 bg-white/80",
                      )}
                      aria-hidden="true"
                      data-testid="inline-product-checkmark"
                    >
                      {isSelected ? (
                        <Check className="h-4 w-4" strokeWidth={3} />
                      ) : null}
                    </span>
                  </div>
                  <div className="px-[12px] py-[10px]">
                    <p
                      className="line-clamp-1 text-[14px] font-medium tracking-[-0.35px] text-grayscale-800"
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
            className="rounded-[8px] bg-red-h-50 p-[12px] text-[13px] font-medium text-red-h-500"
            data-testid="inline-product-submit-error"
          >
            {errorMessage}
          </p>
        ) : null}
      </div>

      {showCapSnackbar ? (
        <div data-testid="inline-product-cap-snackbar">
          <Snackbar
            tone="warning"
            position="bottom-center"
            title={`최대 ${cap}개까지 선택할 수 있어요`}
            body="적게 고르면 나머지는 AI가 자동으로 채워줘요"
            onClose={() => setShowCapSnackbar(false)}
          />
        </div>
      ) : null}
    </div>
  );
}
