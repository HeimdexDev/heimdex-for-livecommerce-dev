"use client";

import { useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import { getActiveSubtitles } from "../lib/source-time";
import { formatTimelineTimestamp } from "../lib/timeline-math";
import { resolveFontFamily } from "@/lib/fonts";
import { usePlaybackSync } from "../hooks/usePlaybackSync";
import { useOrgSettings } from "@/lib/orgSettings";
import { getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

interface PreviewPanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  playheadMs: number;
  isPlaying: boolean;
  totalDurationMs: number;
  selectedSubtitleIndex: number | null;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
  onSelectSubtitle: (index: number | null) => void;
  onUpdateSubtitlePosition: (index: number, positionX: number, positionY: number) => void;
  onUpdateSubtitleFontSize: (index: number, fontSizePx: number) => void;
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
  selectedSubtitleIndex,
  onPlayheadChange,
  onPlayingChange,
  onSelectSubtitle,
  onUpdateSubtitlePosition,
  onUpdateSubtitleFontSize,
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

  const containerRef = useRef<HTMLDivElement>(null);
  const [isHovering, setIsHovering] = useState(false);
  const showTransport = isHovering || isPlaying;
  const dragRef = useRef<{
    mode: "move" | "resize";
    subtitleIndex: number;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    origFontSizePx: number;
    lockedWidth: number | null;
  } | null>(null);

  const getSubtitleIndex = useCallback((subtitleId: string): number => {
    return subtitles.findIndex((s) => s.id === subtitleId);
  }, [subtitles]);

  const handleMovePointerDown = useCallback((e: React.PointerEvent, sub: EditorSubtitle) => {
    e.preventDefault();
    e.stopPropagation();
    const idx = getSubtitleIndex(sub.id);
    if (idx < 0) return;

    onSelectSubtitle(idx);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);

    // Lock the element width to prevent reflow during drag
    const el = (e.target as HTMLElement).closest("[data-subtitle-box]") as HTMLElement | null;
    const lockedWidth = el ? el.offsetWidth : null;

    dragRef.current = {
      mode: "move",
      subtitleIndex: idx,
      startX: e.clientX,
      startY: e.clientY,
      origX: sub.style.positionX,
      origY: sub.style.positionY,
      origFontSizePx: sub.style.fontSizePx,
      lockedWidth,
    };
  }, [getSubtitleIndex, onSelectSubtitle]);

  const handleResizePointerDown = useCallback((e: React.PointerEvent, sub: EditorSubtitle) => {
    e.preventDefault();
    e.stopPropagation();
    const idx = getSubtitleIndex(sub.id);
    if (idx < 0) return;

    (e.target as HTMLElement).setPointerCapture(e.pointerId);

    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();
    const centerX = rect.left + sub.style.positionX * rect.width;
    const centerY = rect.top + sub.style.positionY * rect.height;
    const startDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);

    dragRef.current = {
      mode: "resize",
      subtitleIndex: idx,
      startX: startDist, // reuse startX to store initial distance
      startY: 0,
      origX: sub.style.positionX,
      origY: sub.style.positionY,
      origFontSizePx: sub.style.fontSizePx,
      lockedWidth: null,
    };
  }, [getSubtitleIndex]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    const drag = dragRef.current;
    const container = containerRef.current;
    if (!drag || !container) return;

    const rect = container.getBoundingClientRect();

    if (drag.mode === "move") {
      const deltaX = (e.clientX - drag.startX) / rect.width;
      const deltaY = (e.clientY - drag.startY) / rect.height;
      const newX = Math.max(0, Math.min(1, drag.origX + deltaX));
      const newY = Math.max(0, Math.min(1, drag.origY + deltaY));
      onUpdateSubtitlePosition(drag.subtitleIndex, newX, newY);
    } else {
      const centerX = rect.left + drag.origX * rect.width;
      const centerY = rect.top + drag.origY * rect.height;
      const currentDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);
      const initialDist = drag.startX; // stored initial distance
      if (initialDist < 1) return;
      const scale = currentDist / initialDist;
      const newSize = Math.round(Math.max(8, Math.min(200, drag.origFontSizePx * scale)));
      onUpdateSubtitleFontSize(drag.subtitleIndex, newSize);
    }
  }, [onUpdateSubtitlePosition, onUpdateSubtitleFontSize]);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-3 p-4"
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      {/* Preview container — matches org aspect ratio */}
      <div
        ref={containerRef}
        className={cn(
          "relative w-full overflow-hidden rounded-lg bg-black",
          aspectRatio === "9:16" ? "aspect-[9/16] max-w-[280px]" : "aspect-video max-w-[480px]",
        )}
        onClick={() => onSelectSubtitle(null)}
      >
        {/* Main video element */}
        <video
          ref={videoRef}
          className="h-full w-full object-contain"
          playsInline
          onSeeked={onSeeked}
          onEnded={onEnded}
        />

        {/* Subtitle overlay */}
        {activeSubtitles.map((sub) => {
          const idx = getSubtitleIndex(sub.id);
          const isSelected = idx >= 0 && idx === selectedSubtitleIndex;
          const isDraggingThis = dragRef.current?.subtitleIndex === idx && dragRef.current?.mode === "move";

          return (
            <div
              key={sub.id}
              data-subtitle-box
              className={cn(
                "absolute",
                isSelected ? "cursor-grab z-10" : "cursor-grab",
              )}
              style={{
                left: `${sub.style.positionX * 100}%`,
                top: `${sub.style.positionY * 100}%`,
                transform: "translate(-50%, -50%)",
                pointerEvents: "auto",
                ...(isDraggingThis && dragRef.current?.lockedWidth
                  ? { width: `${dragRef.current.lockedWidth}px` }
                  : {}),
              }}
              onPointerDown={(e) => handleMovePointerDown(e, sub)}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onClick={(e) => e.stopPropagation()}
            >
              {sub.text === "" ? (
                <div
                  aria-label="empty text overlay placeholder"
                  className={cn(
                    "h-16 w-16 rounded bg-red-500",
                    isSelected && "ring-2 ring-indigo-400 ring-offset-1",
                  )}
                />
              ) : (
                <p
                  className={cn(
                    "whitespace-pre-wrap select-none text-center",
                    isSelected && "rounded ring-2 ring-indigo-400 ring-offset-1",
                  )}
                  style={{
                    fontFamily: resolveFontFamily(sub.style.fontFamily),
                    fontSize: `${Math.max(8, sub.style.fontSizePx * 0.5)}px`,
                    color: sub.style.fontColor,
                    fontWeight: sub.style.fontWeight,
                    textAlign: "center",
                    padding: "2px 6px",
                    borderRadius: "2px",
                    ...(sub.style.backgroundColor
                      ? {
                          backgroundColor: sub.style.backgroundColor,
                          opacity: sub.style.backgroundOpacity,
                        }
                      : {}),
                  }}
                >
                  {sub.text}
                </p>
              )}

              {/* Resize corner handles */}
              {isSelected && (
                <>
                  {(["nw", "ne", "sw", "se"] as const).map((corner) => (
                    <div
                      key={corner}
                      className={cn(
                        "absolute h-3 w-3 rounded-full bg-indigo-500 border-2 border-white",
                        corner === "nw" && "-top-1.5 -left-1.5 cursor-nwse-resize",
                        corner === "ne" && "-top-1.5 -right-1.5 cursor-nesw-resize",
                        corner === "sw" && "-bottom-1.5 -left-1.5 cursor-nesw-resize",
                        corner === "se" && "-bottom-1.5 -right-1.5 cursor-nwse-resize",
                      )}
                      onPointerDown={(e) => handleResizePointerDown(e, sub)}
                      onPointerMove={handlePointerMove}
                      onPointerUp={handlePointerUp}
                    />
                  ))}
                </>
              )}
            </div>
          );
        })}

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

      {/* Transport controls — fade on idle, always shown while playing */}
      <div
        className={cn(
          "flex w-full max-w-[280px] flex-col gap-2 transition-opacity duration-200",
          showTransport ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      >
        {/* Progress bar */}
        <div className="relative h-1 w-full rounded-full bg-gray-300">
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
                ? "bg-gray-900 text-white hover:bg-gray-700"
                : "cursor-not-allowed bg-gray-200 text-gray-400",
            )}
          >
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>

          <span className="font-mono text-xs text-gray-600">
            {formatTimelineTimestamp(playheadMs)} / {formatTimelineTimestamp(totalDurationMs)}
          </span>
        </div>
      </div>
    </div>
  );
}
