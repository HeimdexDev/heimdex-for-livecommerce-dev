import { SceneThumbnail } from "@/components/SceneThumbnail";
import type { PreeditRow } from "../lib/types";

interface SequenceItemProps {
  row: PreeditRow;
  index: number;
}

export function SequenceItem({ row, index }: SequenceItemProps) {
  const scene = row.selectedScene;

  if (!scene) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed border-gray-200 p-2">
        <span className="text-xs font-medium text-gray-400">{index + 1}</span>
        <span className="truncate text-xs text-gray-400">
          {row.label || "미선택"}
        </span>
      </div>
    );
  }

  const durationSec = Math.round((scene.endMs - scene.startMs) / 1000);

  return (
    <div className="flex items-center gap-2 rounded-md border border-gray-200 bg-white p-2">
      <span className="text-xs font-medium text-gray-500">{index + 1}</span>
      <div className="h-8 w-14 flex-shrink-0 overflow-hidden rounded bg-gray-100">
        <SceneThumbnail
          videoId={scene.videoId}
          sceneId={scene.sceneId}
          agentAvailable={false}
          className="h-full w-full object-cover"
        />
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-gray-700">
          {row.label || scene.videoTitle || "장면"}
        </p>
        <p className="text-[10px] text-gray-400">{durationSec}s</p>
      </div>
    </div>
  );
}
