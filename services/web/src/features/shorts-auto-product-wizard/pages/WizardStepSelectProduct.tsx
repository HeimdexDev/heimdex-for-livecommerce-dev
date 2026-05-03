// ============================================================================
// Step 3 — 제품 선택 (product select)
//
// On mount: kick off enumeration (idempotent — POST /products/{id}/scan
// dedupes via the v1 service's in-flight check) and poll the catalog
// every 5s until entries arrive or the timeout fires. User picks one
// product card; "다음" submits the scan_order with catalog_entry_id baked
// in. Worker filters its catalog fetch to that single entry (Phase A
// backend in PR #134).
//
// Criteria values flow in via URL search params (Criteria → SelectProduct
// is one-way; back-navigation loses the form — Phase D polish will add
// URL-param prefill on the Criteria step). The values are passed through
// to createScanOrder verbatim.
// ============================================================================

"use client";

import { useRouter, useSearchParams } from "next/navigation";
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
import type {
  CatalogProductSummary,
  Language,
  ProductDistribution,
  ScanIntent,
} from "@/lib/types/shorts-auto-product-wizard";

import { WizardLayout } from "../components/WizardLayout";

interface Props {
  videoId: string;
}

const POLL_INTERVAL_MS = 5_000;
// Enumeration on a typical 5–10 min livecommerce VOD takes 30–90s on
// the warm Aircloud container; 3 min ceiling covers cold-start +
// HuggingFace download on a fresh container without waiting forever.
const POLL_TIMEOUT_MS = 180_000;

interface ParsedCriteria {
  length_seconds: number;
  requested_count: number;
  time_range_start_ms: number | null;
  time_range_end_ms: number | null;
  product_distribution: ProductDistribution;
  language: Language;
  intent: ScanIntent;
}

/**
 * Read URL search params into the criteria shape. Returns null when any
 * required field is missing or out of range — caller redirects back to
 * the criteria step. Values are clamped to the same bounds the backend
 * validates so a malformed URL doesn't 422 us silently mid-submit.
 */
function parseCriteriaFromUrl(
  params: URLSearchParams,
): ParsedCriteria | null {
  const length = Number(params.get("length"));
  const count = Number(params.get("count"));
  const dist = params.get("distribution");
  const lang = params.get("language");
  const intent = params.get("intent") ?? "commit";
  if (!Number.isInteger(length) || length < 10 || length > 120) return null;
  if (!Number.isInteger(count) || count < 1 || count > 50) return null;
  if (dist !== "single" && dist !== "multi") return null;
  if (lang !== "ko" && lang !== "en") return null;
  if (intent !== "commit" && intent !== "preview") return null;
  const startRaw = params.get("start");
  const endRaw = params.get("end");
  const start = startRaw && startRaw !== "" ? Number(startRaw) : null;
  const end = endRaw && endRaw !== "" ? Number(endRaw) : null;
  return {
    length_seconds: length,
    requested_count: count,
    time_range_start_ms: start,
    time_range_end_ms: end,
    product_distribution: dist,
    language: lang,
    intent,
  };
}

export function WizardStepSelectProduct({ videoId }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { getAccessToken } = useAuth();

  // Criteria from URL — if missing/malformed, kick back to step 2.
  // Convert Next's ReadonlyURLSearchParams → standard URLSearchParams
  // so the pure helper has no Next.js coupling (and stays unit-testable).
  const criteria = parseCriteriaFromUrl(
    new URLSearchParams(searchParams?.toString() ?? ""),
  );

  const [entries, setEntries] = useState<CatalogProductSummary[]>([]);
  const [pollState, setPollState] = useState<
    "enumerating" | "ready" | "no_products" | "error"
  >("enumerating");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Bumped by the "다시 시도" button to re-enter the effect — without
  // this, retry would only reset local state and the polling closure
  // would never re-fire (codex P2, Phase B follow-up).
  const [retryCount, setRetryCount] = useState(0);
  // Ref + state separation: state for re-render, ref for the polling
  // closure to read latest selection without re-creating the interval.
  const startedAtRef = useRef<number>(Date.now());

  // Single effect handles both: trigger enumeration, then poll
  // catalog. Combining them avoids a flicker where the catalog endpoint
  // 200s with empty entries before enumeration even fires.
  useEffect(() => {
    if (!criteria) {
      router.replace(
        `/export/shorts/auto/wizard/${encodeURIComponent(videoId)}/criteria`,
      );
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (cancelled) return;
      try {
        const resp = await getProductCatalog(videoId, getAccessToken);
        if (cancelled) return;
        if (resp.entries.length > 0) {
          setEntries(resp.entries);
          setPollState("ready");
          return; // stop polling
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
      // Trigger is best-effort: if it transiently fails (network blip,
      // service hiccup) but the video already has a catalog from a
      // prior wizard run, the user can still pick from the cached
      // entries. Don't terminate on trigger failure — let the catalog
      // poll be the source of truth. The poll's own error / timeout
      // paths handle the "no cached catalog AND trigger failed" case.
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
          "[wizard] triggerEnumeration failed; will still poll catalog",
          err,
        );
      }
      // Fire the first poll immediately — covers the common case where
      // the catalog was already populated from a prior wizard run on
      // the same video (deduped triggerEnumeration returns instantly).
      void poll();
    };

    void start();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // criteria reference changes on every render (parseCriteriaFromUrl
    // returns a new object); we only care about videoId stability.
    // retryCount is in the deps so the "다시 시도" button can re-enter
    // this effect (codex P2). router.refresh() alone is insufficient —
    // it doesn't change deps, so the effect wouldn't re-fire.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, getAccessToken, router, retryCount]);

  const handleSubmit = useCallback(async () => {
    if (!criteria || !selectedId) return;
    setErrorMessage(null);
    setSubmitting(true);
    try {
      const response = await createScanOrder(
        videoId,
        { ...criteria, catalog_entry_id: selectedId },
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
        setErrorMessage(err instanceof Error ? err.message : "Unknown error");
      }
      setSubmitting(false);
    }
  }, [criteria, selectedId, videoId, getAccessToken, router]);

  // Pass criteria back through to /criteria so the user can adjust
  // without losing it. Same URL params shape this page reads on mount.
  const backHref = criteria
    ? `/export/shorts/auto/wizard/${encodeURIComponent(videoId)}/criteria`
    : `/export/shorts/auto/wizard`;

  return (
    <WizardLayout
      currentStep={3}
      heading="쇼츠 주제로 사용할 제품을 선택하세요"
      next={{
        label: submitting ? "생성 중..." : "다음 >",
        onClick: handleSubmit,
        disabled: !selectedId || submitting || pollState !== "ready",
      }}
      backHref={backHref}
    >
      {pollState === "enumerating" ? (
        <div
          className="space-y-3 rounded-lg border border-gray-200 bg-white p-6 text-center"
          data-testid="enumeration-loading"
        >
          <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
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
          className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-6"
          data-testid="no-products"
        >
          <h2 className="text-lg font-semibold text-amber-900">
            제품을 찾을 수 없어요
          </h2>
          <p className="text-sm text-amber-800">
            이 영상에서 자동으로 인식할 수 있는 제품이 없습니다. 다른
            영상을 선택하거나, 영상에 제품이 잘 보이는 시간 구간을
            지정해 보세요.
          </p>
        </div>
      ) : null}

      {pollState === "error" ? (
        <div
          className="space-y-3 rounded-lg border border-red-200 bg-red-50 p-6"
          data-testid="poll-error"
        >
          <h2 className="text-lg font-semibold text-red-900">
            제품 스캔에 실패했어요
          </h2>
          <p className="text-sm text-red-800">
            {errorMessage ?? "잠시 후 다시 시도해 주세요."}
          </p>
          <button
            type="button"
            onClick={() => {
              startedAtRef.current = Date.now();
              setEntries([]);
              setSelectedId(null);
              setErrorMessage(null);
              setPollState("enumerating");
              // Bumps the effect's deps → re-fires triggerEnumeration +
              // poll. router.refresh() would re-fetch the RSC tree but
              // wouldn't re-key the client effect, leaving the user on
              // the loading state with no new API calls.
              setRetryCount((n) => n + 1);
            }}
            className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700"
          >
            다시 시도
          </button>
        </div>
      ) : null}

      {pollState === "ready" ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            아래 제품 중 하나를 클릭해 선택하세요.
          </p>
          <div
            className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4"
            data-testid="product-grid"
          >
            {entries.map((entry) => {
              const isSelected = entry.catalog_entry_id === selectedId;
              return (
                <button
                  key={entry.catalog_entry_id}
                  type="button"
                  onClick={() => setSelectedId(entry.catalog_entry_id)}
                  className={[
                    "group flex flex-col gap-2 rounded-lg border bg-white p-3 text-left transition",
                    isSelected
                      ? "border-indigo-500 ring-2 ring-indigo-200"
                      : "border-gray-200 hover:border-indigo-300",
                  ].join(" ")}
                  data-testid="product-card"
                  data-selected={isSelected}
                >
                  <div className="aspect-square overflow-hidden rounded bg-gray-100">
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
                  </div>
                  <p
                    className="line-clamp-2 text-sm font-medium text-gray-900"
                    title={entry.label}
                  >
                    {entry.label}
                  </p>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span>인식 신뢰도</span>
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-200">
                      <div
                        className="h-full bg-indigo-400"
                        style={{
                          width: `${Math.round(entry.enumeration_confidence * 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
          {errorMessage ? (
            <p
              className="rounded-md bg-red-50 p-3 text-sm text-red-700"
              data-testid="submit-error"
            >
              {errorMessage}
            </p>
          ) : null}
        </div>
      ) : null}
    </WizardLayout>
  );
}
