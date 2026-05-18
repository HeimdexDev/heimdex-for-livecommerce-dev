// ============================================================================
// Auto-shorts wizard — loading screen.
//
// Subscribes to the parent job's aggregate status via useScanOrder (3s
// polling) and presents a progress bar + per-child status chips while
// renders are in flight. As soon as ANY child render reaches
// ``render_status === "completed"`` the page redirects to /edit-clips —
// regardless of parent stage. EditClipsPage owns its own useScanOrder
// instance and continues polling for late-arriving siblings.
//
// Why not wait for parent terminal: parent stage only flips to
// ``committed`` after *every* child reaches a terminal stage. In a
// 1-of-N success scenario (one render finishes far ahead of its
// siblings) the old "parent terminal AND any completed" predicate
// stalled — the user had to reload to see results.
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
import { LoadingShortsProgress } from "../components/LoadingShortsProgress";
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
  /** Parent stage is failure-terminal, OR parent reached success-terminal
   *  with every child in failed/cancelled state. */
  failure: boolean;
  /** At least one child has ``render_status === "completed"`` — an MP4
   *  is viewable in /edit-clips regardless of parent stage. */
  redirectable: boolean;
}

function deriveState(status: ScanOrderStatusResponse | null): DerivedState {
  if (!status) return { failure: false, redirectable: false };
  const parentStage = status.parent.stage;
  // Parent explicitly failed or cancelled — no MP4 will ever land.
  if (FAILURE_STAGES.has(parentStage)) {
    return { failure: true, redirectable: false };
  }
  // Any child render produced an MP4 → redirect immediately. Parent
  // stage is intentionally ignored: in a 1-of-N success scenario the
  // parent sits at ``fanned_out`` until every sibling reaches a
  // terminal stage, which can be tens of seconds after the first
  // render lands.
  const anyRenderCompleted = status.children.some(
    (c: JobStatusResponse) => c.render_status === "completed",
  );
  if (anyRenderCompleted) {
    return { failure: false, redirectable: true };
  }
  // Whole-batch failure: parent reached terminal-success AND every
  // child settled into a no-MP4 terminal state. The terminal stages
  // are ``done | failed | cancelled``; given the early return above
  // we already know no child reached ``render_status === "completed"``,
  // so a child stuck at ``done`` here was completed by
  // ``children/runner.py::_complete_no_render`` (no-mentions /
  // transcript-unavailable / live-block-too-short). Without this
  // branch the user stares at the loading spinner forever — there's
  // nothing for the redirect to point at, but the UI never surfaces
  // a friendly message either.
  if (
    SUCCESS_STAGES.has(parentStage) &&
    status.children_total > 0 &&
    status.children.length === status.children_total &&
    status.children.every(
      (c: JobStatusResponse) =>
        c.stage === "done" ||
        c.stage === "failed" ||
        c.stage === "cancelled",
    )
  ) {
    return { failure: true, redirectable: false };
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
          childJobs={status?.children ?? []}
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
  // Distinct failure shapes — distinguish so the user gets a precise
  // explanation rather than a generic "something broke":
  //   1. Parent has an error_code      → friendlyParentError
  //   2. Parent stage = cancelled      → "취소되었어요"
  //   3. All children completed without producing a render — covers
  //      the ``_complete_no_render`` paths from the STT pipeline
  //      (no_mentions / transcript_unavailable / live_block_too_short).
  //      The runner doesn't set error_code on the parent for these,
  //      so they reach FailureState via ``deriveState``'s
  //      "all children terminal AND no render produced" predicate.
  //      → "쇼츠를 만들 수 있는 구간을 찾지 못했어요"
  //   4. All children failed (rare;    → "생성 요청한 모든 쇼츠가 실패했어요"
  //      parent terminal-success but
  //      children_failed === total)
  const allChildrenDoneNoRender =
    status.children_total > 0 &&
    status.children.length === status.children_total &&
    status.children.every(
      (c) =>
        c.stage === "done" && c.render_status !== "completed",
    );

  let body: string;
  if (parentError) {
    body = parentError;
  } else if (status.parent.stage === "cancelled") {
    body = "취소되었어요.";
  } else if (allChildrenDoneNoRender) {
    body =
      "선택하신 영상에서는 쇼츠를 만들 수 있는 구간을 찾지 못했어요. " +
      "다른 길이나 다른 영상을 시도해 주세요.";
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
  childJobs: JobStatusResponse[];
  onCancel?: () => void;
}

function LoadingState({ count, childJobs, onCancel }: LoadingStateProps) {
  // Before fan-out lands ``children_total`` is 0 — no per-clip data to
  // show, so render the indeterminate spinner. Once the parent's
  // children fan out we have a concrete N and live per-child stages,
  // which the progress component visualizes as a determinate bar +
  // chips.
  const hasChildren = count > 0;
  return (
    <div
      className="grid gap-6 md:grid-cols-[260px_1fr]"
      data-testid="wizard-loading-state"
    >
      <LoadingShortsSkeleton count={count} />
      <div className="flex min-h-[420px] items-center justify-center rounded-lg border border-gray-200 bg-white">
        {hasChildren ? (
          <LoadingShortsProgress
            children={childJobs}
            childrenTotal={count}
            onCancel={onCancel}
          />
        ) : (
          <LoadingShortsSpinner onCancel={onCancel} />
        )}
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
