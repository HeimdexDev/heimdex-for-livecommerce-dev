"use client";

import Link from "next/link";

import { SceneThumbnail } from "@/components/SceneThumbnail";
import { cn } from "@/lib/utils";
import type { AutoClipResponse } from "@/lib/types";

import type { CandidateState } from "../hooks/useCandidateRenderJobs";

interface CandidateCardProps {
  index: number;
  clip: AutoClipResponse;
  videoId: string;
  /** Selection highlight — driven by the parent. */
  isSelected: boolean;
  state: CandidateState;
  onSelect: () => void;
  onDownload: () => void;
  onDelete: () => void;
  /** Deep link into the editor pre-populated with this clip's scenes. */
  editorHref: string;
}

function formatSeconds(ms: number): string {
  return `${Math.round(ms / 1000)}초`;
}

/**
 * One row in the auto-shorts candidate list.
 *
 * Renders in two modes based on ``state.kind``:
 *   - "candidate" / "submitting": fresh AI pick. Shows download + edit
 *     + delete affordances. ``submitting`` disables the buttons + adds
 *     a small spinner.
 *   - "queued" / "rendering": waiting on the render worker. Shows a
 *     status pill ("렌더링 중") and a delete affordance (cancels the job).
 *   - "completed": the render is ready. Download triggers a browser
 *     download via the parent's wired ``onDownload``.
 *   - "failed": render failed. Shows the error message and a delete
 *     affordance to clear the card.
 *
 * Coupling note: this component does NOT call any APIs directly —
 * everything goes through callbacks so testing can mock them and the
 * page-level orchestrator owns the API surface.
 */
export function CandidateCard({
  index,
  clip,
  videoId,
  isSelected,
  state,
  onSelect,
  onDownload,
  onDelete,
  editorHref,
}: CandidateCardProps) {
  const representativeSceneId = clip.scene_ids[0];
  const isInflight =
    state.kind === "submitting" || state.kind === "queued" || state.kind === "rendering";
  const isCompleted = state.kind === "completed";
  const isFailed = state.kind === "failed";

  return (
    <article
      aria-label={`자동 선택 클립 ${index + 1}`}
      aria-selected={isSelected}
      className={cn(
        "group relative flex w-full cursor-pointer gap-3 rounded-lg border p-3 transition-colors",
        isSelected
          ? "border-indigo-400 bg-indigo-50/40 ring-1 ring-inset ring-indigo-200"
          : "border-gray-200 bg-white hover:border-gray-300",
      )}
      onClick={onSelect}
    >
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onSelect();
        }}
        aria-label={`클립 ${index + 1} 선택`}
        className="block h-[120px] w-[80px] flex-shrink-0 overflow-hidden rounded-md bg-gray-200"
      >
        <SceneThumbnail
          videoId={videoId}
          sceneId={representativeSceneId}
          agentAvailable={true}
          className="h-full w-full object-cover"
        />
      </button>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-start justify-between gap-2">
          <span className="text-sm font-bold text-gray-900">클립 {index + 1}</span>
          <StatePill state={state} />
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-gray-500">
          <span>{formatSeconds(clip.duration_ms)}</span>
          <span aria-hidden="true">·</span>
          <span>{clip.scene_ids.length}개 장면</span>
          <span aria-hidden="true">·</span>
          <span>{clip.is_continuous ? "연속" : "선별"}</span>
        </div>

        {isFailed && state.kind === "failed" && (
          <p className="mt-1 line-clamp-2 text-[11px] text-red-500">
            {state.error}
          </p>
        )}

        <div className="mt-auto flex items-center gap-1.5 pt-2" onClick={(e) => e.stopPropagation()}>
          {!isCompleted && !isFailed && (
            <Link
              href={editorHref}
              className="inline-flex items-center rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-700 transition-colors hover:bg-gray-50"
              aria-label={`클립 ${index + 1} 편집`}
              onClick={(e) => e.stopPropagation()}
            >
              편집
            </Link>
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              if (isCompleted || state.kind === "candidate") onDownload();
            }}
            disabled={isInflight || (state.kind !== "candidate" && state.kind !== "completed")}
            className={cn(
              "inline-flex items-center rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
              isInflight
                ? "cursor-not-allowed bg-indigo-200 text-white"
                : isCompleted
                  ? "bg-emerald-500 text-white hover:bg-emerald-600"
                  : "bg-indigo-500 text-white hover:bg-indigo-600",
            )}
            aria-label={
              isCompleted
                ? `클립 ${index + 1} 다운로드`
                : `클립 ${index + 1} 렌더링 후 다운로드`
            }
          >
            {state.kind === "submitting" && "요청 중..."}
            {state.kind === "queued" && "렌더링 중"}
            {state.kind === "rendering" && "렌더링 중"}
            {state.kind === "completed" && "다운로드"}
            {(state.kind === "candidate" || state.kind === "failed") && "다운로드"}
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="inline-flex items-center rounded-md border border-gray-200 bg-white px-2 py-1 text-[11px] font-medium text-gray-500 transition-colors hover:bg-red-50 hover:text-red-600"
            aria-label={`클립 ${index + 1} 삭제`}
          >
            삭제
          </button>
        </div>
      </div>
    </article>
  );
}

function StatePill({ state }: { state: CandidateState }) {
  if (state.kind === "candidate") return null;
  if (state.kind === "submitting") {
    return <Pill className="bg-amber-100 text-amber-700">요청 중</Pill>;
  }
  if (state.kind === "queued") {
    return <Pill className="bg-amber-100 text-amber-700">대기 중</Pill>;
  }
  if (state.kind === "rendering") {
    return <Pill className="bg-amber-100 text-amber-700">렌더링 중</Pill>;
  }
  if (state.kind === "completed") {
    return <Pill className="bg-emerald-100 text-emerald-700">완료</Pill>;
  }
  return <Pill className="bg-red-100 text-red-700">실패</Pill>;
}

function Pill({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium",
        className,
      )}
    >
      {children}
    </span>
  );
}
