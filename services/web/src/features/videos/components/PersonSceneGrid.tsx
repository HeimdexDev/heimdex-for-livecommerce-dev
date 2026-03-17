"use client";

import { SceneThumbnail } from "@/components/SceneThumbnail";
import { formatTimestamp } from "@/lib/api/utils";
import { cn } from "@/lib/utils";
import { getPersonGridClass, getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";
import type { VideoScene } from "@/lib/types";

export interface PersonSceneGridProps {
  scenes: VideoScene[];
  videoId: string;
  agentAvailable: boolean;
  aspectRatio: ThumbnailAspectRatio;
  onSceneClick?: (startMs: number) => void;
}

function EmptyState() {
  return (
    <div className="flex items-center justify-center rounded-lg border border-dashed border-gray-200 py-8">
      <p className="text-sm text-gray-400">이 영상에서 등장하는 장면이 없습니다.</p>
    </div>
  );
}

export function PersonSceneGrid({
  scenes,
  videoId,
  agentAvailable,
  aspectRatio,
  onSceneClick,
}: PersonSceneGridProps) {
  if (scenes.length === 0) {
    return (
      <div>
        <h3 className="text-sm font-semibold text-gray-900">
          등장 장면
        </h3>
        <div className="mt-2">
          <EmptyState />
        </div>
      </div>
    );
  }

  const caption = (scene: VideoScene): string => {
    const text = scene.scene_caption?.trim() || scene.transcript_raw?.trim() || "";
    return text.length > 50 ? text.slice(0, 50) + "..." : text;
  };

  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-900">
        등장 장면
        <span className="ml-1.5 text-xs font-normal text-gray-500">({scenes.length}개)</span>
      </h3>
      <div className="mt-2 max-h-[340px] overflow-y-auto rounded-lg">
        <div className={cn("grid", getPersonGridClass(aspectRatio))}>
          {scenes.map((scene) => (
            <button
              key={scene.scene_id}
              type="button"
              onClick={() => onSceneClick?.(scene.start_ms)}
              className="group text-left"
            >
              <div className="relative overflow-hidden rounded-lg">
                <SceneThumbnail
                  videoId={videoId}
                  sceneId={scene.scene_id}
                  agentAvailable={agentAvailable}
                  className={cn("w-full rounded-lg", getThumbnailAspectClass(aspectRatio))}
                />
                <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
                  {formatTimestamp(scene.start_ms)}
                </span>
                <div className="absolute inset-0 bg-black/0 transition-colors group-hover:bg-black/20 rounded-lg" />
              </div>
              {caption(scene) && (
                <p className="mt-1 line-clamp-1 text-xs text-gray-500">
                  {caption(scene)}
                </p>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
