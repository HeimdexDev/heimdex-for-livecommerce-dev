"use client";

import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import { getActiveSubtitles } from "../lib/source-time";
import { formatTimelineTimestamp } from "../lib/timeline-math";
import { usePlaybackSync } from "../hooks/usePlaybackSync";
import { useOrgSettings } from "@/lib/orgSettings";
import { getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

interface PreviewPanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  playheadMs: number;
  isPlaying: boolean;
  totalDurationMs: number;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
}

function PlayIcon() {
  return (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
  );
}

export function PreviewPanel({
  clips,
  subtitles,
  playheadMs,
  isPlaying,
  totalDurationMs,
  onPlayheadChange,
  onPlayingChange,
}: PreviewPanelProps) {
  const {
    videoRef,
    preloadRef,
    togglePlay,
    onSeeked,
    onEnded,
  } = usePlaybackSync({
    clips,
    playheadMs,
    isPlaying,
    onPlayheadChange,
    onPlayingChange,
  });

  const { settings } = useOrgSettings();
  const aspectRatio = settings.thumbnail_aspect_ratio as ThumbnailAspectRatio;

  const activeSubtitles = getActiveSubtitles(subtitles, playheadMs);
  const progressPct = totalDurationMs > 0 ? (playheadMs / totalDurationMs) * 100 : 0;

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-4">
      {/* Preview container — matches org aspect ratio */}
      <div className={cn(
        "relative w-full overflow-hidden rounded-lg bg-black",
        aspectRatio === "9:16" ? "aspect-[9/16] max-w-[280px]" : "aspect-video max-w-[480px]",
      )}>
        {/* Main video element */}
        <video
          ref={videoRef}
          className="h-full w-full object-contain"
          playsInline
          onSeeked={onSeeked}
          onEnded={onEnded}
        />

        {/* Subtitle overlay */}
        {activeSubtitles.map((sub) => (
          <div
            key={sub.id}
            className="pointer-events-none absolute inset-x-0"
            style={{
              top: `${sub.style.positionY * 100}%`,
              transform: "translateY(-50%)",
            }}
          >
            <p
              className="mx-auto w-fit max-w-[90%] text-center"
              style={{
                fontFamily: sub.style.fontFamily,
                fontSize: `${Math.max(8, sub.style.fontSizePx * 0.5)}px`, // Scale down for preview
                color: sub.style.fontColor,
                fontWeight: sub.style.fontWeight,
                textAlign: "center",
                ...(sub.style.backgroundColor
                  ? {
                      backgroundColor: sub.style.backgroundColor,
                      padding: "2px 6px",
                      borderRadius: "2px",
                      opacity: sub.style.backgroundOpacity,
                    }
                  : {}),
              }}
            >
              {sub.text}
            </p>
          </div>
        ))}

        {/* No clips placeholder */}
        {clips.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500">
            <span className="text-xs">장면을 추가하세요</span>
          </div>
        )}

        {/* Preload hidden video for next clip */}
        <video
          ref={preloadRef}
          className="hidden"
          preload="auto"
          muted
          playsInline
        />
      </div>

      {/* Transport controls */}
      <div className="flex w-full max-w-[280px] flex-col gap-2">
        {/* Progress bar */}
        <div className="relative h-1 w-full rounded-full bg-gray-700">
          <div
            className="absolute left-0 top-0 h-full rounded-full bg-indigo-500 transition-[width] duration-75"
            style={{ width: `${Math.min(100, progressPct)}%` }}
          />
        </div>

        {/* Play button + time display */}
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={togglePlay}
            disabled={clips.length === 0}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-full transition-colors",
              clips.length > 0
                ? "bg-white text-gray-900 hover:bg-gray-200"
                : "bg-gray-700 text-gray-500 cursor-not-allowed",
            )}
          >
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>

          <span className="font-mono text-xs text-gray-400">
            {formatTimelineTimestamp(playheadMs)} / {formatTimelineTimestamp(totalDurationMs)}
          </span>
        </div>
      </div>
    </div>
  );
}
