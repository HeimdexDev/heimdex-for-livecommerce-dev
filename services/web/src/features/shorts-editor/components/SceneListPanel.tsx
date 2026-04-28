"use client";

import { useMemo, useState, useEffect } from "react";
import type { VideoScene } from "@/lib/types";
import type { EditorClip } from "../lib/types";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { SpeakerTranscriptDisplay } from "@/lib/speaker-transcript-display";
import { Pagination } from "@/components/ui/Pagination";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 10;

interface SceneListPanelProps {
  videoId: string;
  scenes: VideoScene[];
  clips: EditorClip[];
  selectedClipIndex: number | null;
  onToggleScene: (scene: VideoScene) => void;
  onSelectClip: (index: number) => void;
  onPreview?: (clipIndex: number) => void;
  onExport?: () => void;
}

function formatTime(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function SceneListPanel({
  videoId,
  scenes,
  clips,
  selectedClipIndex,
  onToggleScene,
  onSelectClip,
  onPreview,
  onExport,
}: SceneListPanelProps) {
  const clipSceneIds = useMemo(
    () => new Set(clips.map((c) => c.sceneId)),
    [clips],
  );

  const clipIndexBySceneId = useMemo(() => {
    const map = new Map<string, number>();
    clips.forEach((c, i) => map.set(c.sceneId, i));
    return map;
  }, [clips]);

  const activeCount = clipSceneIds.size;

  // Client-side pagination over the already-fetched scenes (max 200 / fetch).
  const [currentPage, setCurrentPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(scenes.length / PAGE_SIZE));

  // Snap back to page 1 if the underlying list shrinks past the current page
  // (e.g., scenes refetched from a shorter video).
  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(1);
  }, [currentPage, totalPages]);

  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pageScenes = scenes.slice(pageStart, pageStart + PAGE_SIZE);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">장면 목록</h3>
            <span className="text-xs text-gray-400">
              {scenes.length}개 · {activeCount}개 선택
            </span>
          </div>
          <div className="flex gap-2">
            {onExport && (
              <button
                type="button"
                onClick={onExport}
                disabled={activeCount === 0}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                내보내기
              </button>
            )}
            {onPreview && (
              <button
                type="button"
                onClick={() => selectedClipIndex != null && onPreview(selectedClipIndex)}
                disabled={selectedClipIndex == null}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                미리보기
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Scene list (paginated) */}
      <div className="flex-1 overflow-y-auto">
        {pageScenes.map((scene, pageIdx) => {
          const globalIndex = pageStart + pageIdx;
          const isActive = clipSceneIds.has(scene.scene_id);
          const clipIdx = clipIndexBySceneId.get(scene.scene_id);
          const isSelected = isActive && clipIdx != null && clipIdx === selectedClipIndex;

          return (
            <div
              key={scene.scene_id}
              role="button"
              tabIndex={0}
              onClick={() => {
                if (isActive && clipIdx != null) onSelectClip(clipIdx);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && isActive && clipIdx != null) onSelectClip(clipIdx);
              }}
              className={cn(
                "w-full cursor-pointer border-b border-gray-100 p-3 text-left transition-colors hover:bg-gray-50",
                isActive && !isSelected && "border-l-4 border-l-indigo-300 bg-indigo-50/30",
                isSelected &&
                  "border-l-4 border-l-blue-500 bg-blue-50/60 ring-1 ring-inset ring-blue-300",
              )}
            >
              <div className="flex items-start gap-3">
                {/* Toggle checkbox */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleScene(scene);
                  }}
                  aria-pressed={isActive}
                  aria-label={`${globalIndex + 1}번 장면 ${isActive ? "해제" : "선택"}`}
                  className={cn(
                    "mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded border-2 transition-colors",
                    isActive
                      ? "border-blue-500 bg-blue-500 hover:border-blue-600 hover:bg-blue-600"
                      : "border-gray-300 bg-white hover:border-blue-400",
                  )}
                >
                  {isActive && (
                    <svg className="h-3 w-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  )}
                </button>

                {/* Thumbnail */}
                <div className="relative h-10 w-16 flex-shrink-0 overflow-hidden rounded bg-gray-200">
                  <SceneThumbnail
                    videoId={videoId}
                    sceneId={scene.scene_id}
                    agentAvailable={false}
                    className="h-full w-full"
                    sourceType="gdrive"
                  />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-gray-700">
                        장면 {globalIndex + 1}
                      </span>
                      {(scene.speaker_count ?? 0) > 1 && (
                        <span className="inline-flex items-center rounded-full bg-gray-100 px-1.5 py-0.5 text-[9px] font-medium text-gray-500">
                          {scene.speaker_count}명
                        </span>
                      )}
                    </div>
                    <span className="font-mono text-[10px] text-gray-400">
                      {formatTime(scene.start_ms)} - {formatTime(scene.end_ms)}
                    </span>
                  </div>

                  {/* Speaker-diarized transcript (preferred) */}
                  {scene.speaker_transcript ? (
                    <SpeakerTranscriptDisplay
                      transcript={scene.speaker_transcript}
                      className="mb-1.5"
                    />
                  ) : scene.transcript_raw ? (
                    <p className="mb-1.5 line-clamp-2 text-xs text-gray-500">
                      {scene.transcript_raw}
                    </p>
                  ) : scene.scene_caption ? (
                    <p className="mb-1.5 line-clamp-2 text-xs italic text-gray-400">
                      {scene.scene_caption}
                    </p>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}

        {scenes.length === 0 && (
          <div className="flex items-center justify-center p-8 text-gray-400">
            <p className="text-xs">장면 정보를 불러올 수 없습니다</p>
          </div>
        )}
      </div>

      {/* Pagination */}
      {scenes.length > PAGE_SIZE && (
        <div className="border-t border-gray-200 px-4 py-2">
          <Pagination
            currentPage={currentPage}
            totalPages={totalPages}
            onPageChange={setCurrentPage}
            ariaLabel="장면 페이지"
          />
        </div>
      )}
    </div>
  );
}
