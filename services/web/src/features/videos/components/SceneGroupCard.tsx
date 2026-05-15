"use client";

import { useState } from "react";
import { formatTimestamp } from "@/lib/api/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { cn } from "@/lib/utils";
import { SceneCard } from "./VideoDetailPage";
import type { SceneGroup } from "@/lib/types";
import type { ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

export function SceneGroupCard({
  group,
  videoId,
  agentAvailable,
  onSeekToScene,
  activeSceneMs,
  aspectRatio,
}: {
  group: SceneGroup;
  videoId: string;
  agentAvailable: boolean;
  onSeekToScene?: (startMs: number) => void;
  activeSceneMs?: number | null;
  aspectRatio: ThumbnailAspectRatio;
}) {
  const [expanded, setExpanded] = useState(false);

  const timeRange = `${formatTimestamp(group.start_ms)} — ${formatTimestamp(group.end_ms)}`;
  const repScene = group.scenes.find(
    (s) => s.scene_id === group.representative_scene_id,
  ) ?? group.scenes[0];
  const isPortrait = aspectRatio === "9:16";

  return (
    <div
      className={cn(
        "overflow-hidden border",
        isPortrait
          ? "rounded-card border-grayscale-100 bg-grayscale-10"
          : "rounded-xl border-gray-200 bg-gray-50",
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className={cn(
          "flex w-full items-center gap-4 px-4 py-3 text-left transition-colors",
          isPortrait ? "hover:bg-grayscale-100/40" : "hover:bg-gray-100",
        )}
      >
        {repScene && (
          <div
            className={cn(
              "flex-shrink-0 overflow-hidden",
              isPortrait ? "h-24 w-14 rounded-md" : "h-14 w-24 rounded-lg",
            )}
          >
            <SceneThumbnail
              videoId={videoId}
              sceneId={repScene.scene_id}
              agentAvailable={agentAvailable}
              className="h-full w-full object-cover"
            />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "text-sm font-medium",
                isPortrait ? "text-grayscale-800" : "text-gray-800",
              )}
            >
              {timeRange}
            </span>
            <span
              className={cn(
                "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                isPortrait
                  ? "border border-heimdex-navy-500 text-heimdex-navy-500"
                  : "bg-indigo-50 text-indigo-600",
              )}
            >
              {group.scene_count}개 장면
            </span>
          </div>
        </div>

        <svg
          className={cn(
            "h-4 w-4 flex-shrink-0 transition-transform",
            isPortrait ? "text-grayscale-500" : "text-gray-400",
            expanded && "rotate-180",
          )}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {expanded && (
        <div
          className={cn(
            "space-y-3 border-t bg-white px-4 py-4",
            isPortrait ? "border-grayscale-100" : "border-gray-200",
          )}
        >
          {group.scenes.map((scene, i) => (
            <SceneCard
              key={scene.scene_id}
              scene={scene}
              index={i}
              videoId={videoId}
              agentAvailable={agentAvailable}
              isSelected={false}
              onToggle={() => {}}
              onSeek={onSeekToScene}
              isPlaying={activeSceneMs === scene.start_ms}
              aspectRatio={aspectRatio}
            />
          ))}
        </div>
      )}
    </div>
  );
}
