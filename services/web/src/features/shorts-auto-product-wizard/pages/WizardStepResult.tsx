// ============================================================================
// Auto-shorts wizard — loading screen.
//
// Subscribes to the parent job's aggregate status via useScanOrder (3s
// polling) and presents a friendly skeleton-rail + spinner UI while
// renders are in flight. As soon as the parent reaches a terminal-success
// stage AND at least one child render completes, the page redirects the
// operator straight to the inline subtitle editor (/edit-clips). On
// failure (parent failed/cancelled, or every child failed) the page
// surfaces ``friendlyParentError`` and a back link.
//
// The legacy per-child cards (title edit, render-result link, script
// editor link) are intentionally gone — auto-redirect makes them
// unreachable in the success path, and the inline editor at /edit-clips
// already owns those affordances.
//
// Loose-coupling: this page does NOT import from features/shorts-render
// or features/shorts-editor. Navigation flows via Next ``router.replace``
// URL strings only.
// ============================================================================

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef } from "react";

import type {
  JobStatusResponse,
  ScanOrderStatusResponse,
  ScanStage,
} from "@/lib/types/shorts-auto-product-wizard";
import { useAuth } from "@/lib/auth";

import { InlineWizardBreadcrumb } from "../components/InlineWizardBreadcrumb";
import { LoadingShortsSkeleton } from "../components/LoadingShortsSkeleton";
import { LoadingShortsSpinner } from "../components/LoadingShortsSpinner";
import { useScanOrder } from "../hooks/useScanOrder";

interface Props {
  videoId: string;
  parentJobId: string;
}

const SUCCESS_STAGES: ReadonlySet<ScanStage> = new Set<ScanStage>([
  "done",
  "committed",
]);

const FAILURE_STAGES: ReadonlySet<ScanStage> = new Set<ScanStage>([
  "failed",
  "cancelled",
]);

interface DerivedState {
  /** All children failed, OR parent stage itself is failure-terminal. */
  failure: boolean;
  /** Parent reached success-terminal AND ≥1 child render completed. */
  redirectable: boolean;
}

function deriveState(status: ScanOrderStatusResponse | null): DerivedState {
  if (!status) return { failure: false, redirectable: false };
  const parentStage = status.parent.stage;
  if (FAILURE_STAGES.has(parentStage)) {
    return { failure: true, redirectable: false };
  }
  // Whole-batch failure: parent looks "done" but every child failed. Without
  // this branch the user lands on /edit-clips with nothing to edit.
  if (
    SUCCESS_STAGES.has(parentStage) &&
    status.children_total > 0 &&
    status.children_failed === status.children_total
  ) {
    return { failure: true, redirectable: false };
  }
  const anyCompleted = status.children.some(
    (c: JobStatusResponse) => c.render_status === "completed",
  );
  if (SUCCESS_STAGES.has(parentStage) && anyCompleted) {
    return { failure: false, redirectable: true };
  }
  return { failure: false, redirectable: false };
}

export function WizardStepResult({ videoId, parentJobId }: Props) {
  const { getAccessToken } = useAuth();
  const router = useRouter();
  const { status, error, cancel } = useScanOrder(parentJobId, getAccessToken);

  const { failure, redirectable } = useMemo(() => deriveState(status), [status]);

  // Fire ``router.replace`` exactly once when the redirect predicate becomes
  // true. ``router.replace`` (not push) keeps the browser back-button from
  // trapping the user on a now-stale spinner. The ref guards against the
  // effect firing multiple times if useScanOrder's status updates after the
  // redirect has already kicked off (next.js navigation is async).
  const redirectedRef = useRef(false);
  useEffect(() => {
    if (!redirectable || redirectedRef.current) return;
    redirectedRef.current = true;
    router.replace(
      `/export/shorts/auto/wizard/${encodeURIComponent(
        videoId,
      )}/result/${encodeURIComponent(parentJobId)}/edit-clips`,
    );
  }, [redirectable, router, videoId, parentJobId]);

  return (
    <div
      className="mx-auto max-w-5xl space-y-6 p-6"
      data-testid="wizard-step-result"
    >
      <header className="flex items-center justify-between gap-4">
        <Link
          href={`/videos/${encodeURIComponent(videoId)}?view=auto-shorts`}
          className="text-sm text-gray-500 hover:text-gray-700"
          data-testid="result-back-link"
        >
          &lt; 뒤로가기
        </Link>
        <InlineWizardBreadcrumb variant="two-step" currentStep={2} />
      </header>

      {error ? (
        <div
          className="rounded-md bg-red-50 p-3 text-sm text-red-700"
          data-testid="wizard-status-error"
        >
          상태 조회 실패: {error.message}
        </div>
      ) : null}

      {failure && status ? (
        <FailureState status={status} />
      ) : (
        <LoadingState
          count={status?.children_total ?? 0}
          // Cancellation is meaningful only while we're actually loading.
          // Once redirect has fired the page is about to unmount; hide the
          // button to avoid a doomed POST race.
          onCancel={redirectedRef.current ? undefined : () => void cancel()}
        />
      )}
    </div>
  );
}

interface FailureStateProps {
  status: ScanOrderStatusResponse;
}

function FailureState({ status }: FailureStateProps) {
  const parentError = status.parent.error_code
    ? friendlyParentError(status.parent.error_code, status.parent.error_message)
    : null;
  // Three distinct failure shapes — distinguish so the user gets a precise
  // explanation rather than a generic "something broke":
  //   1. Parent has an error_code      → friendlyParentError
  //   2. Parent stage = cancelled      → "취소되었어요"
  //   3. All children failed (rare;    → "생성 요청한 모든 쇼츠가 실패했어요"
  //      parent terminal-success but
  //      children_failed === total)
  let body: string;
  if (parentError) {
    body = parentError;
  } else if (status.parent.stage === "cancelled") {
    body = "취소되었어요.";
  } else if (
    status.children_total > 0 &&
    status.children_failed === status.children_total
  ) {
    body = "생성 요청한 모든 쇼츠가 실패했어요. 잠시 후 다시 시도해 주세요.";
  } else {
    body = "쇼츠 생성에 실패했어요. 잠시 후 다시 시도해 주세요.";
  }
  return (
    <div
      className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-6"
      data-testid="wizard-failure-state"
    >
      <h2 className="text-base font-semibold text-red-800">
        쇼츠 생성에 실패했어요
      </h2>
      <p className="text-sm text-red-700">{body}</p>
    </div>
  );
}

interface LoadingStateProps {
  count: number;
  onCancel?: () => void;
}

function LoadingState({ count, onCancel }: LoadingStateProps) {
  return (
    <div
      className="grid gap-6 md:grid-cols-[260px_1fr]"
      data-testid="wizard-loading-state"
    >
      <LoadingShortsSkeleton count={count} />
      <div className="flex min-h-[420px] items-center justify-center rounded-lg border border-gray-200 bg-white">
        <LoadingShortsSpinner onCancel={onCancel} />
      </div>
    </div>
  );
}

/**
 * Map known parent-job error codes to user-facing Korean messages.
 * Unknown codes fall back to the raw code + message so a backend
 * regression that adds a new code surfaces visibly rather than
 * disappearing into a generic "오류" blob.
 *
 * Exported for unit tests.
 */
export function friendlyParentError(
  errorCode: string,
  errorMessage: string | null,
): string {
  switch (errorCode) {
    case "proxy_missing":
      return (
        "이 영상은 아직 트랜스코딩이 완료되지 않았어요. 영상 목록에서 " +
        "체크 표시가 뜬 다음 다시 시도해 주세요."
      );
    default:
      return `오류: ${errorCode}${errorMessage ? ` — ${errorMessage}` : ""}`;
  }
}
