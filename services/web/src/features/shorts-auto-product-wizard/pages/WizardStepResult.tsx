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
import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  getShortComposition,
  updateRenderJobTitle,
} from "@/lib/api/shorts-render";
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
            <ChildList children={status.children} videoId={videoId} />
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
  videoId: string;
}

function ChildList({ children, videoId }: ChildListProps) {
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
        <ChildCard key={child.job_id} child={child} videoId={videoId} />
      ))}
    </div>
  );
}

function ChildCard({
  child,
  videoId,
}: {
  child: JobStatusResponse;
  videoId: string;
}) {
  const isDone = child.stage === "done" || child.stage === "committed";
  const isFailed = child.stage === "failed";
  const hasRender = child.render_job_id !== null && isDone;
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
      {hasRender && child.render_job_id ? (
        <ChildRenderActions
          renderJobId={child.render_job_id}
          videoId={videoId}
        />
      ) : null}
      {isFailed && child.error_message ? (
        <p className="mt-1 text-xs text-red-700">{child.error_message}</p>
      ) : null}
    </div>
  );
}

/**
 * Per-card actions surfaced once the child reaches a terminal-with-render
 * state. Three affordances:
 *
 *   1. **Title edit** (inline): pencil → input → save; uses
 *      ``updateRenderJobTitle``. Optimistic-update with rollback on error
 *      so the user sees their edit immediately. Empty trimmed input
 *      submits ``null`` to clear the title (matches backend semantics).
 *   2. **렌더 결과 보기**: link to the existing render-result route
 *      that lives in the shorts-render feature. We do NOT cross-import
 *      from features/shorts-render — just route via Next href.
 *   3. **스크립트 편집**: fetch the render job's composition spec on
 *      click → derive scene_ids → route to the existing /export/shorts/editor
 *      with ?videoId=...&sceneIds=... — same query-param contract the
 *      v1 auto-shorts dashboard already uses.
 *
 * Loose-coupling: this component imports from ``@/lib/api/shorts-render``
 * (allowed — it's the public surface) but NOT from ``@/features/shorts-render``
 * or ``@/features/shorts-editor``. Routes carry the contract.
 */
function ChildRenderActions({
  renderJobId,
  videoId,
}: {
  renderJobId: string;
  videoId: string;
}) {
  const router = useRouter();
  const { getAccessToken } = useAuth();

  // Title edit local state. ``displayedTitle`` is what the card shows;
  // it stays in sync with the server after a successful save and rolls
  // back on error. ``draftTitle`` is the input's edited value while the
  // user is typing.
  const [displayedTitle, setDisplayedTitle] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [titleError, setTitleError] = useState<string | null>(null);

  // 편집 (open editor) state — single in-flight fetch lock + error.
  const [isOpeningEditor, setIsOpeningEditor] = useState(false);
  const [editorError, setEditorError] = useState<string | null>(null);

  const handleEditClick = () => {
    setDraftTitle(displayedTitle ?? "");
    setIsEditing(true);
    setTitleError(null);
  };

  const handleSave = async () => {
    const trimmed = draftTitle.trim();
    const next = trimmed.length === 0 ? null : trimmed;
    const previous = displayedTitle;
    // Optimistic update — close the editor + reflect the new title
    // before the server confirms. Rollback on failure.
    setDisplayedTitle(next);
    setIsEditing(false);
    setIsSaving(true);
    setTitleError(null);
    try {
      await updateRenderJobTitle(renderJobId, next, getAccessToken);
    } catch (err) {
      setDisplayedTitle(previous);
      setTitleError(err instanceof Error ? err.message : "저장 실패");
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenEditor = async () => {
    setEditorError(null);
    setIsOpeningEditor(true);
    try {
      const response = await getShortComposition(renderJobId, getAccessToken);
      const sceneIds = extractSceneIds(response.composition);
      if (sceneIds.length === 0) {
        setEditorError("이 쇼츠에는 편집할 장면이 없습니다.");
        return;
      }
      const params = new URLSearchParams({
        videoId,
        sceneIds: sceneIds.join(","),
      });
      router.push(`/export/shorts/editor?${params.toString()}`);
    } catch (err) {
      setEditorError(
        err instanceof Error ? err.message : "에디터 열기 실패",
      );
    } finally {
      setIsOpeningEditor(false);
    }
  };

  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-2 text-xs">
        <span className="text-gray-500">제목:</span>
        {isEditing ? (
          <>
            <input
              type="text"
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              placeholder="(제목 없음)"
              className="flex-1 rounded-md border border-gray-300 px-2 py-1 text-xs"
              data-testid={`child-title-input-${renderJobId}`}
              autoFocus
            />
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={isSaving}
              className="rounded-md bg-indigo-500 px-2 py-1 text-xs text-white hover:bg-indigo-600 disabled:bg-gray-300"
              data-testid={`child-title-save-${renderJobId}`}
            >
              저장
            </button>
            <button
              type="button"
              onClick={() => {
                setIsEditing(false);
                setTitleError(null);
              }}
              disabled={isSaving}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
              data-testid={`child-title-cancel-${renderJobId}`}
            >
              취소
            </button>
          </>
        ) : (
          <>
            <span
              className="flex-1 truncate text-gray-800"
              data-testid={`child-title-display-${renderJobId}`}
            >
              {displayedTitle ?? <span className="text-gray-400">(제목 없음)</span>}
            </span>
            <button
              type="button"
              onClick={handleEditClick}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
              data-testid={`child-title-edit-${renderJobId}`}
            >
              제목 편집
            </button>
          </>
        )}
      </div>
      {titleError ? (
        <p className="text-xs text-red-700">{titleError}</p>
      ) : null}
      <div className="flex gap-2 text-xs">
        <Link
          href={`/export/shorts/render/${renderJobId}`}
          className="text-indigo-600 hover:underline"
          data-testid={`child-view-render-${renderJobId}`}
        >
          렌더 결과 보기
        </Link>
        <button
          type="button"
          onClick={() => void handleOpenEditor()}
          disabled={isOpeningEditor}
          className="text-indigo-600 hover:underline disabled:text-gray-400"
          data-testid={`child-open-editor-${renderJobId}`}
        >
          {isOpeningEditor ? "여는 중..." : "스크립트 편집"}
        </button>
      </div>
      {editorError ? (
        <p className="text-xs text-red-700">{editorError}</p>
      ) : null}
    </div>
  );
}

/**
 * Pull scene_ids out of the loosely-typed CompositionResponse.composition
 * field. Defensive: backend's ``CompositionResponse.composition`` is
 * ``Record<string, unknown>`` because the same shape is used by both
 * the rendered job's persisted spec AND a generated draft, so the FE
 * type doesn't pin scene_clips. Cast carefully here and fall back to
 * an empty list if the shape isn't what we expect — caller surfaces
 * a friendly error.
 */
function extractSceneIds(composition: Record<string, unknown>): string[] {
  const clips = composition.scene_clips;
  if (!Array.isArray(clips)) return [];
  const ids: string[] = [];
  for (const clip of clips) {
    if (
      clip &&
      typeof clip === "object" &&
      "scene_id" in clip &&
      typeof (clip as { scene_id: unknown }).scene_id === "string"
    ) {
      ids.push((clip as { scene_id: string }).scene_id);
    }
  }
  return ids;
}
