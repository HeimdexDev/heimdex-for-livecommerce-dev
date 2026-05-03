// ============================================================================
// Step 4 — 쇼츠 자동 생성 (results)
//
// Subscribes to the parent job's aggregate status via useScanOrder
// (3s polling). Renders parent progress + a list of N child status cards
// keyed on ``shorts_index``. When a child reaches ``done`` with
// ``render_job_id`` set, the card surfaces a download/preview link routed
// through the existing shorts-render endpoints.
//
// Loose-coupling: this page does NOT import from features/shorts-render
// or features/shorts-editor. It links to those routes via Next ``href``
// strings only.
// ============================================================================

"use client";

import Link from "next/link";

import { useAuth } from "@/lib/auth";
import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";

import { WizardLayout } from "../components/WizardLayout";
import { useScanOrder } from "../hooks/useScanOrder";

interface Props {
  videoId: string;
  parentJobId: string;
}

export function WizardStepResult({ videoId, parentJobId }: Props) {
  const { getAccessToken } = useAuth();
  const { status, error, isPolling, cancel } = useScanOrder(
    parentJobId,
    getAccessToken,
  );

  return (
    <WizardLayout
      currentStep={4}
      heading="쇼츠 자동 생성"
      next={null}
      backHref={`/export/shorts/auto/wizard/${encodeURIComponent(videoId)}/criteria`}
    >
      <div className="space-y-4">
        {error ? (
          <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
            상태 조회 실패: {error.message}
          </div>
        ) : null}

        {!status ? (
          <div className="rounded-md border border-gray-200 bg-white p-6 text-sm text-gray-600">
            상태를 불러오는 중...
          </div>
        ) : (
          <>
            <ParentProgress
              parent={status.parent}
              childrenComplete={status.children_complete}
              childrenFailed={status.children_failed}
              childrenTotal={status.children_total}
              isPolling={isPolling}
              onCancel={cancel}
            />
            <ChildList children={status.children} />
          </>
        )}
      </div>
    </WizardLayout>
  );
}

interface ParentProgressProps {
  parent: JobStatusResponse;
  childrenComplete: number;
  childrenFailed: number;
  childrenTotal: number;
  isPolling: boolean;
  onCancel: () => Promise<void>;
}

function ParentProgress({
  parent,
  childrenComplete,
  childrenFailed,
  childrenTotal,
  isPolling,
  onCancel,
}: ParentProgressProps) {
  const showCancel =
    parent.stage !== "done" &&
    parent.stage !== "committed" &&
    parent.stage !== "failed" &&
    parent.stage !== "cancelled";

  return (
    <div className="space-y-2 rounded-lg border border-gray-200 bg-white p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">
            전체 진행률
          </h2>
          <p className="text-xs text-gray-500">
            {isPolling ? "3초마다 갱신" : "완료"}
          </p>
        </div>
        {showCancel ? (
          <button
            type="button"
            onClick={() => void onCancel()}
            className="rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
            data-testid="cancel-scan-order"
          >
            전체 취소
          </button>
        ) : null}
      </div>
      <div className="text-sm text-gray-700">
        단계: <span className="font-medium">{parent.stage}</span> ·{" "}
        진행률: {parent.progress_pct}%
        {parent.progress_label ? ` · ${parent.progress_label}` : null}
      </div>
      <div className="text-sm text-gray-700">
        쇼츠 진행: {childrenComplete} 완료 · {childrenFailed} 실패 ·{" "}
        총 {childrenTotal}개
      </div>
      {parent.error_code ? (
        <p
          className="rounded-md bg-red-50 p-2 text-xs text-red-700"
          data-testid="parent-error"
        >
          오류: {parent.error_code}
          {parent.error_message ? ` — ${parent.error_message}` : ""}
        </p>
      ) : null}
    </div>
  );
}

interface ChildListProps {
  children: JobStatusResponse[];
}

function ChildList({ children }: ChildListProps) {
  if (children.length === 0) {
    return (
      <div className="rounded-md border border-gray-200 bg-white p-4 text-sm text-gray-500">
        아직 생성된 쇼츠가 없습니다.
      </div>
    );
  }
  // Sort by shorts_index so the visual order matches "쇼츠 1, 2, 3, ..."
  const sorted = [...children].sort(
    (a, b) => (a.shorts_index ?? 0) - (b.shorts_index ?? 0),
  );
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {sorted.map((child) => (
        <ChildCard key={child.job_id} child={child} />
      ))}
    </div>
  );
}

function ChildCard({ child }: { child: JobStatusResponse }) {
  const isDone = child.stage === "done" || child.stage === "committed";
  const isFailed = child.stage === "failed";
  return (
    <div
      className={`rounded-md border p-4 ${
        isFailed
          ? "border-red-200 bg-red-50"
          : isDone
            ? "border-green-200 bg-green-50"
            : "border-gray-200 bg-white"
      }`}
      data-testid={`child-card-${child.shorts_index ?? "unknown"}`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">
          쇼츠 {child.shorts_index ?? "?"}
        </h3>
        <span className="text-xs text-gray-500">{child.stage}</span>
      </div>
      <p className="text-xs text-gray-600">진행률 {child.progress_pct}%</p>
      {child.render_job_id ? (
        <Link
          href={`/export/shorts/render/${child.render_job_id}`}
          className="mt-2 inline-block text-xs text-indigo-600 hover:underline"
        >
          렌더 결과 보기 &rarr;
        </Link>
      ) : null}
      {isFailed && child.error_message ? (
        <p className="mt-1 text-xs text-red-700">{child.error_message}</p>
      ) : null}
    </div>
  );
}
