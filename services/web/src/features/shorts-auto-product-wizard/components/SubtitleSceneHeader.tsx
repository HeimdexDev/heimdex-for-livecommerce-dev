// ============================================================================
// "장면N  HH:MM:SS – HH:MM:SS  Ns" header rendered above each scene's cue
// list inside the 자막 tab. Pure presentational.
// ============================================================================

"use client";

import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

interface Props {
  /** 1-based scene index for "장면N" display. */
  sceneIndex: number;
  /** Output-timeline start in ms. */
  startMs: number;
  /** Output-timeline end in ms. */
  endMs: number;
  /** Cue count badge — drives the "(N자막)" hint shown next to the label. */
  cueCount?: number;
  className?: string;
}

export function SubtitleSceneHeader({
  sceneIndex,
  startMs,
  endMs,
  cueCount,
  className,
}: Props) {
  const durationSec = Math.max(0, Math.round((endMs - startMs) / 1000));
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded bg-gray-50 px-3 py-2 text-xs",
        className,
      )}
      data-testid={`subtitle-scene-header-${sceneIndex}`}
    >
      <span className="font-semibold text-gray-700">장면{sceneIndex}</span>
      <span className="text-gray-500">
        {formatVideoTimestampHMS(startMs)} – {formatVideoTimestampHMS(endMs)}
      </span>
      <span className="text-gray-500">{durationSec}초</span>
      {typeof cueCount === "number" ? (
        <span className="ml-auto text-gray-400" data-testid="scene-header-cue-count">
          {cueCount}자막
        </span>
      ) : null}
    </div>
  );
}
