import { SceneThumbnail } from "@/components/SceneThumbnail";
import type { PreeditScene } from "../lib/types";

interface SelectedSceneSlotProps {
  scene: PreeditScene | null;
  onClear: () => void;
  formatMs: (ms: number) => string;
}

export function SelectedSceneSlot({
  scene,
  onClear,
  formatMs,
}: SelectedSceneSlotProps) {
  if (!scene) {
    return (
      <div className="flex items-center justify-center rounded-lg border-2 border-dashed border-gray-300 py-4 text-sm text-gray-400">
        장면을 검색하여 선택하세요
      </div>
    );
  }

  const durationSec = Math.round((scene.endMs - scene.startMs) / 1000);

  const snippetPreview = scene.snippet
    ? scene.snippet.length > 120
      ? scene.snippet.slice(0, 120) + "..."
      : scene.snippet
    : null;

  return (
    <div className="rounded-lg border border-indigo-200 bg-indigo-50/50 p-3">
      <div className="flex items-center gap-3">
        <div className="h-16 w-28 flex-shrink-0 overflow-hidden rounded bg-gray-200">
          <SceneThumbnail
            videoId={scene.videoId}
            sceneId={scene.sceneId}
            agentAvailable={false}
            className="h-full w-full object-cover"
          />
        </div>
        <div className="min-w-0 flex-1">
          <p className="line-clamp-1 text-sm font-medium text-gray-800">
            {scene.videoTitle || scene.videoId}
          </p>
          <p className="text-xs text-gray-500">
            {formatMs(scene.startMs)} - {formatMs(scene.endMs)} ({durationSec}s)
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="flex-shrink-0 rounded-md border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-50"
        >
          변경
        </button>
      </div>
      {snippetPreview && (
        <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-gray-500">
          {snippetPreview}
        </p>
      )}
    </div>
  );
}
