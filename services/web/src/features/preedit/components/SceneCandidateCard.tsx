import { SceneThumbnail } from "@/components/SceneThumbnail";
import type { SceneResult } from "@/lib/types";

interface SceneCandidateCardProps {
  scene: SceneResult;
  onSelect: () => void;
  onPreview: () => void;
}

function formatMs(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function SceneCandidateCard({ scene, onSelect, onPreview }: SceneCandidateCardProps) {
  const duration = scene.end_ms - scene.start_ms;
  const durationSec = Math.round(duration / 1000);

  return (
    <div className="flex min-w-0 flex-col overflow-hidden rounded-lg border border-gray-200 bg-white transition-shadow hover:shadow-md">
      {/* Thumbnail + Info — clickable for preview */}
      <button
        type="button"
        onClick={onPreview}
        className="cursor-pointer text-left transition-colors hover:bg-gray-50"
      >
        <div className="relative aspect-video w-full overflow-hidden bg-gray-100">
          <SceneThumbnail
            videoId={scene.video_id}
            sceneId={scene.scene_id}
            agentAvailable={false}
            className="h-full w-full object-cover"
          />
          <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
            {durationSec}s
          </span>
        </div>

        <div className="flex flex-1 flex-col gap-1 p-2">
          <p className="truncate text-xs font-medium text-gray-700">
            {scene.video_title || scene.video_id}
          </p>
          <p className="text-[10px] text-gray-500">
            {formatMs(scene.start_ms)} - {formatMs(scene.end_ms)}
          </p>
          {scene.snippet && (
            <p className="line-clamp-2 text-[11px] leading-tight text-gray-500">
              {scene.snippet}
            </p>
          )}
        </div>
      </button>

      {/* Select button — separate action */}
      <div className="border-t border-gray-100 p-2">
        <button
          type="button"
          onClick={onSelect}
          className="w-full rounded-md bg-indigo-50 py-1 text-xs font-medium text-indigo-600 transition-colors hover:bg-indigo-100"
        >
          선택
        </button>
      </div>
    </div>
  );
}
