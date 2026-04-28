"use client";

import { cn } from "@/lib/utils";
import type { AutoClipResponse } from "@/lib/types";

import { useAutoShortsClipPlayback } from "../hooks/useAutoShortsClipPlayback";

interface CenterPlayerProps {
  clip: AutoClipResponse | null;
  videoId: string;
  isLoadingSelection?: boolean;
}

function formatSeconds(ms: number): string {
  return `${Math.round(ms / 1000)}초`;
}

/**
 * Center-pane proxy-stitched player.
 *
 * Plays a candidate clip's members back-to-back against the source
 * video's proxy URL by seeking forward when each member's ``end_ms`` is
 * reached. No render is required to preview — the user can flip
 * between candidates without spinning up render jobs.
 *
 * Renders a 9:16 frame on a vertical, neutral background to match the
 * shorts aspect ratio (and the reference design). On wider candidates
 * we letterbox; ``object-contain`` keeps the proxy from getting
 * cropped weirdly.
 */
export function CenterPlayer({ clip, videoId, isLoadingSelection }: CenterPlayerProps) {
  const {
    videoRef,
    playbackUrl,
    isPlaying,
    currentMemberIdx,
    totalSourceDurationMs,
    togglePlay,
    onLoadedMetadata,
    onTimeUpdate,
    onEnded,
  } = useAutoShortsClipPlayback({ clip, videoId });

  if (isLoadingSelection) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-500">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-500" />
          <span>하이라이트를 분석하고 있어요...</span>
        </div>
      </div>
    );
  }

  if (!clip || !playbackUrl) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        <p>클립을 선택하면 미리 볼 수 있어요</p>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-3 p-4">
      <div className="relative aspect-[9/16] h-full max-h-[640px] overflow-hidden rounded-xl bg-black shadow">
        <video
          ref={videoRef}
          src={playbackUrl}
          className="h-full w-full object-contain"
          playsInline
          onLoadedMetadata={onLoadedMetadata}
          onTimeUpdate={onTimeUpdate}
          onEnded={onEnded}
        >
          브라우저가 비디오 재생을 지원하지 않습니다.
        </video>

        {/* Bottom transport bar — translucent so it overlays the proxy
            cleanly without re-doing layout math. */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/70 to-transparent p-3 text-xs text-white">
          <button
            type="button"
            onClick={togglePlay}
            aria-label={isPlaying ? "일시정지" : "재생"}
            className="pointer-events-auto flex h-8 w-8 items-center justify-center rounded-full bg-white/90 text-indigo-700 transition-colors hover:bg-white"
          >
            {isPlaying ? (
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
                <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
            )}
          </button>
          <span className={cn("font-mono", "text-white/80")}>
            장면 {Math.min(currentMemberIdx + 1, clip.members.length)} / {clip.members.length}
            <span className="mx-1.5 text-white/40">·</span>
            {formatSeconds(totalSourceDurationMs)}
          </span>
        </div>
      </div>
    </div>
  );
}
