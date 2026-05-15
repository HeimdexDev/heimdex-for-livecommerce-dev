"use client";

import type { AutoSelectResponse, ScoringModeRequest } from "@/lib/types";

import { CandidateCard } from "./CandidateCard";
import { EmptyState } from "./EmptyState";
import { MODE_OPTIONS } from "../lib/types";
import {
  clipKeyOf,
  type CandidateState,
} from "../hooks/useCandidateRenderJobs";

interface CandidateListProps {
  videoId: string;
  selection: AutoSelectResponse | null;
  mode: ScoringModeRequest;
  isLoading: boolean;
  selectedClipKey: string | null;
  onSelectClip: (clipKey: string) => void;
  onDownloadClip: (clipKey: string) => void;
  onDeleteClip: (clipKey: string) => void;
  /** Resolves a clip's state from the render-jobs map. */
  getState: (clipKey: string) => CandidateState;
  /** Build editor deep link for a clip. */
  buildEditorHref: (sceneIds: string[]) => string;
}

/**
 * Left rail of the auto-shorts page. Renders a header with the mode
 * summary + per-mode count, then a vertical list of ``CandidateCard``s.
 * Mode switching lives in the page-level ``ModeTabs`` strip above this
 * panel — PR 5 dropped the inline 재선택 link in favor of always-visible
 * tabs. (Phase 1 had a 재선택 link that opened ``ModeReselectModal``.)
 */
export function CandidateList({
  videoId,
  selection,
  mode,
  isLoading,
  selectedClipKey,
  onSelectClip,
  onDownloadClip,
  onDeleteClip,
  getState,
  buildEditorHref,
}: CandidateListProps) {
  const modeOption = MODE_OPTIONS.find((m) => m.value === mode);
  const modeLabel = modeOption?.label ?? mode;
  const clipCount = selection?.clips.length ?? 0;
  const totalSeconds = selection
    ? Math.round(selection.total_duration_ms / 1000)
    : 0;
  const scorerLabel = selection?.scorer === "llm" ? "AI 선택" : null;

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-gray-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-gray-900">
          생성된 쇼츠 {clipCount > 0 && <span className="text-gray-400">({clipCount})</span>}
        </h2>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-gray-500">
          <span className="font-medium text-gray-700">{modeLabel} 모드</span>
          {clipCount > 0 && (
            <>
              <span aria-hidden="true">·</span>
              <span>총 {totalSeconds}초</span>
            </>
          )}
          {scorerLabel && (
            <>
              <span aria-hidden="true">·</span>
              <span className="rounded-full bg-indigo-50 px-1.5 py-px text-[10px] font-medium text-indigo-700">
                {scorerLabel}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {isLoading ? (
          <div className="flex flex-col items-center gap-3 py-12 text-sm text-gray-500">
            <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-indigo-500" />
            <span>분석 중...</span>
          </div>
        ) : !selection || clipCount === 0 ? (
          <EmptyState reason={selection?.skipped_reason ?? null} mode={mode} />
        ) : (
          <div className="space-y-2">
            {selection.clips.map((clip, idx) => {
              const key = clipKeyOf(clip);
              return (
                <CandidateCard
                  key={key}
                  index={idx}
                  clip={clip}
                  videoId={videoId}
                  isSelected={key === selectedClipKey}
                  state={getState(key)}
                  onSelect={() => onSelectClip(key)}
                  onDownload={() => onDownloadClip(key)}
                  onDelete={() => onDeleteClip(key)}
                  editorHref={buildEditorHref(clip.scene_ids)}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
