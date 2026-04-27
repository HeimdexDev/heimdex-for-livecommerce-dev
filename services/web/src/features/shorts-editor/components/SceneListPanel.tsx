"use client";

import { useMemo, useState } from "react";
import type { VideoScene } from "@/lib/types";
import type { EditorClip } from "../lib/types";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";
import { cn } from "@/lib/utils";

const MAX_VISIBLE_TURNS = 3;

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

function SpeakerTranscriptDisplay({ transcript }: { transcript: string }) {
  const [expanded, setExpanded] = useState(false);
  const turns = useMemo(() => parseSpeakerTranscript(transcript), [transcript]);

  if (turns.length === 0) return null;

  const visible = expanded ? turns : turns.slice(0, MAX_VISIBLE_TURNS);
  const hasMore = turns.length > MAX_VISIBLE_TURNS;

  return (
    <div className="space-y-1 mb-1.5">
      {visible.map((turn, i) => (
        <div key={i} className="flex items-start gap-1.5">
          <span
            className={cn(
              "inline-flex items-center justify-center shrink-0 rounded px-1 py-0.5 text-[9px] font-semibold leading-none",
              turn.color.bg,
              turn.color.text,
            )}
          >
            {turn.label}
          </span>
          {turn.timestamp && (
            <span className="shrink-0 text-[9px] text-gray-400 font-mono leading-tight pt-0.5">
              {turn.timestamp}
            </span>
          )}
          <p className="text-[11px] text-gray-600 leading-tight line-clamp-2">
            {turn.text}
          </p>
        </div>
      ))}
      {hasMore && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(!expanded);
          }}
          className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium"
        >
          {expanded ? "접기" : `+${turns.length - MAX_VISIBLE_TURNS}개 더보기`}
        </button>
      )}
    </div>
  );
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

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-gray-200 px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900">장면 목록</h3>
            <span className="text-xs text-gray-400">{activeCount}개 선택</span>
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

      {/* Scene list */}
      <div className="flex-1 overflow-y-auto">
        {scenes.map((scene, i) => {
          const isActive = clipSceneIds.has(scene.scene_id);
          const clipIdx = clipIndexBySceneId.get(scene.scene_id);
          const isSelected = isActive && clipIdx != null && clipIdx === selectedClipIndex;

          return (
            <div
              key={scene.scene_id}
              role="button"
              tabIndex={0}
              onClick={() => {
                if (isActive && clipIdx != null) {
                  onSelectClip(clipIdx);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && isActive && clipIdx != null) onSelectClip(clipIdx);
              }}
              className={cn(
                "w-full text-left border-b border-gray-100 p-3 transition-colors hover:bg-gray-50 cursor-pointer",
                isActive && !isSelected && "border-l-3 border-l-indigo-400 bg-indigo-50/40",
                isSelected && "border-l-3 border-l-rose-500 bg-rose-50/60 ring-1 ring-inset ring-rose-300",
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
                  className={cn(
                    "flex-shrink-0 mt-0.5 flex h-5 w-5 items-center justify-center rounded border-2 transition-colors",
                    isActive
                      ? "border-indigo-500 bg-indigo-500 hover:bg-indigo-600 hover:border-indigo-600"
                      : "border-gray-300 bg-white hover:border-indigo-400",
                  )}
                >
                  {isActive && (
                    <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                </button>

                {/* Thumbnail */}
                <div className="relative flex-shrink-0 w-16 h-10 rounded overflow-hidden bg-gray-200">
                  <SceneThumbnail
                    videoId={videoId}
                    sceneId={scene.scene_id}
                    agentAvailable={false}
                    className="w-full h-full"
                    sourceType="gdrive"
                  />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-gray-700">
                        장면 {i + 1}
                      </span>
                      {(scene.speaker_count ?? 0) > 1 && (
                        <span className="inline-flex items-center rounded-full bg-gray-100 px-1.5 py-0.5 text-[9px] font-medium text-gray-500">
                          {scene.speaker_count}명
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-gray-400 font-mono">
                      {formatTime(scene.start_ms)} - {formatTime(scene.end_ms)}
                    </span>
                  </div>

                  {/* Speaker-diarized transcript (preferred) */}
                  {scene.speaker_transcript ? (
                    <SpeakerTranscriptDisplay transcript={scene.speaker_transcript} />
                  ) : scene.transcript_raw ? (
                    <p className="text-xs text-gray-500 line-clamp-2 mb-1.5">
                      {scene.transcript_raw}
                    </p>
                  ) : scene.scene_caption ? (
                    <p className="text-xs text-gray-400 italic line-clamp-2 mb-1.5">
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
    </div>
  );
}
