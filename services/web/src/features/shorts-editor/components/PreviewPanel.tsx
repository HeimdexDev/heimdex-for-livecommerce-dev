"use client";

import { useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import { OverlayRenderer } from "./preview/OverlayRenderer";
import { SubtitleCancelActionBar } from "./SubtitleCancelActionBar";
import { getActiveSubtitles } from "../lib/source-time";
import { formatTimelineTimestamp } from "../lib/timeline-math";
import { resolveFontFamily } from "@/lib/fonts";
import { usePlaybackSync } from "../hooks/usePlaybackSync";
import { getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

interface PreviewPanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  // V2 overlays — rendered alongside subtitles. Empty for V1 sessions.
  overlays?: EditorOverlay[];
  selectedOverlayId?: string | null;
  onSelectOverlay?: (id: string | null) => void;
  // V2 update callback — used for drag (transform.x/y) and resize
  // (fontSizePx for text, transform.widthPx/heightPx for background).
  onUpdateOverlay?: (id: string, updates: Partial<EditorOverlay>) => void;
  // figma 1669:49437 — element selection action bar fires these to delete
  // the currently selected V2 overlay / V1 subtitle. Optional so existing
  // callers don't break; the bar simply hides when omitted.
  onRemoveOverlay?: (id: string) => void;
  onRemoveSubtitle?: (index: number) => void;
  playheadMs: number;
  isPlaying: boolean;
  totalDurationMs: number;
  selectedSubtitleIndex: number | null;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
  onSelectSubtitle: (index: number | null) => void;
  onUpdateSubtitlePosition: (index: number, positionX: number, positionY: number) => void;
  onUpdateSubtitleFontSize: (index: number, fontSizePx: number) => void;
  // when true, the preview container expands to the 352×626 iPhone
  // mockup size used inside FullscreenOverlay. Layout/logic otherwise identical.
  fullscreen?: boolean;
  // playback rate forwarded to <video>. Optional (1.0 default).
  playbackRate?: number;
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
  overlays = [],
  selectedOverlayId = null,
  onSelectOverlay,
  onUpdateOverlay,
  onRemoveOverlay,
  onRemoveSubtitle,
  playheadMs,
  isPlaying,
  totalDurationMs,
  selectedSubtitleIndex,
  onPlayheadChange,
  onPlayingChange,
  onSelectSubtitle,
  onUpdateSubtitlePosition,
  onUpdateSubtitleFontSize,
  fullscreen = false,
  playbackRate,
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
    rate: playbackRate,
  });

  // The shorts editor canvas is always 9:16 (vertical reels/shorts output);
  // the org-wide thumbnail_aspect_ratio setting governs other surfaces.
  const aspectRatio: ThumbnailAspectRatio = "9:16";

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

  // V2 overlay drag state — separate from V1 dragRef so the two paths
  // don't step on each other when a session has both populated.
  const overlayDragRef = useRef<{
    mode: "move" | "resize";
    overlayId: string;
    overlayKind: "text" | "background";
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    origFontSizePx: number;
    origWidthPx: number;
    origHeightPx: number;
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
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();

    // V1 subtitle drag --------------------------------------------------
    const drag = dragRef.current;
    if (drag) {
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
        if (initialDist >= 1) {
          const scale = currentDist / initialDist;
          const newSize = Math.round(Math.max(8, Math.min(200, drag.origFontSizePx * scale)));
          onUpdateSubtitleFontSize(drag.subtitleIndex, newSize);
        }
      }
    }

    // V2 overlay drag --------------------------------------------------
    const ovDrag = overlayDragRef.current;
    if (ovDrag) {
      const overlay = overlays.find((o) => o.id === ovDrag.overlayId);
      if (!overlay || !onUpdateOverlay) return;

      if (ovDrag.mode === "move") {
        const deltaX = (e.clientX - ovDrag.startX) / rect.width;
        const deltaY = (e.clientY - ovDrag.startY) / rect.height;
        const newX = Math.max(0, Math.min(1, ovDrag.origX + deltaX));
        const newY = Math.max(0, Math.min(1, ovDrag.origY + deltaY));
        onUpdateOverlay(ovDrag.overlayId, {
          transform: { ...overlay.transform, x: newX, y: newY },
        } as Partial<EditorOverlay>);
      } else {
        const centerX = rect.left + ovDrag.origX * rect.width;
        const centerY = rect.top + ovDrag.origY * rect.height;
        const currentDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);
        const initialDist = ovDrag.startX;
        if (initialDist >= 1) {
          const scale = currentDist / initialDist;
          if (ovDrag.overlayKind === "text") {
            const newSize = Math.round(
              Math.max(8, Math.min(200, ovDrag.origFontSizePx * scale)),
            );
            onUpdateOverlay(ovDrag.overlayId, {
              fontSizePx: newSize,
            } as Partial<EditorOverlay>);
          } else {
            const newW = Math.round(Math.max(10, Math.min(10000, ovDrag.origWidthPx * scale)));
            const newH = Math.round(Math.max(10, Math.min(10000, ovDrag.origHeightPx * scale)));
            onUpdateOverlay(ovDrag.overlayId, {
              transform: {
                ...overlay.transform,
                widthPx: newW,
                heightPx: newH,
              },
            } as Partial<EditorOverlay>);
          }
        }
      }
    }
  }, [onUpdateSubtitlePosition, onUpdateSubtitleFontSize, onUpdateOverlay, overlays]);

  const handlePointerUp = useCallback(() => {
    dragRef.current = null;
    overlayDragRef.current = null;
  }, []);

  // V2 overlay handlers — body drag = move, corner drag = resize.
  // Selection happens on pointerdown so a drag-without-click still
  // updates the panel selection mid-gesture.
  const handleOverlayMovePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, overlay: EditorOverlay) => {
      e.preventDefault();
      e.stopPropagation();
      onSelectOverlay?.(overlay.id);
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      overlayDragRef.current = {
        mode: "move",
        overlayId: overlay.id,
        overlayKind: overlay.kind,
        startX: e.clientX,
        startY: e.clientY,
        origX: overlay.transform.x,
        origY: overlay.transform.y,
        origFontSizePx:
          overlay.kind === "text" ? overlay.fontSizePx : 0,
        origWidthPx: overlay.transform.widthPx ?? 0,
        origHeightPx: overlay.transform.heightPx ?? 0,
      };
    },
    [onSelectOverlay],
  );

  const handleOverlayResizePointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>, overlay: EditorOverlay) => {
      e.preventDefault();
      e.stopPropagation();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      const container = containerRef.current;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      const centerX = rect.left + overlay.transform.x * rect.width;
      const centerY = rect.top + overlay.transform.y * rect.height;
      const startDist = Math.hypot(e.clientX - centerX, e.clientY - centerY);
      overlayDragRef.current = {
        mode: "resize",
        overlayId: overlay.id,
        overlayKind: overlay.kind,
        startX: startDist, // reuse startX to store initial radial distance
        startY: 0,
        origX: overlay.transform.x,
        origY: overlay.transform.y,
        origFontSizePx:
          overlay.kind === "text" ? overlay.fontSizePx : 0,
        origWidthPx: overlay.transform.widthPx ?? 0,
        origHeightPx: overlay.transform.heightPx ?? 0,
      };
    },
    [],
  );

  return (
    <div
      className="flex h-full flex-col items-center justify-center gap-3 p-4"
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      {/* Preview container — figma 1602:37722: w=352 h=626, rounded-[10px] */}
      <div
        ref={containerRef}
        className={cn(
          "relative overflow-hidden rounded-[10px] bg-black",
          aspectRatio === "9:16"
            ? "w-[352px] h-[626px]"
            : fullscreen
              ? "aspect-video w-full max-w-[626px]"
              : "aspect-video w-full max-w-[480px]",
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
                    isSelected && "ring-2 ring-heimdex-navy-500 ring-offset-1",
                  )}
                />
              ) : (
                <p
                  className={cn(
                    "whitespace-pre-wrap select-none text-center",
                    isSelected && "rounded ring-2 ring-heimdex-navy-500 ring-offset-1",
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
                        "absolute h-3 w-3 rounded-full bg-heimdex-navy-500 border-2 border-white",
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

        {/* V2 overlays — rendered above subtitles. The active-window check
            mirrors getActiveSubtitles: only show overlays whose [start, end)
            includes the current playhead. */}
        {overlays
          .filter((o) => o.startMs <= playheadMs && playheadMs < o.endMs)
          .map((o) => (
            <OverlayRenderer
              key={o.id}
              overlay={o}
              isSelected={selectedOverlayId === o.id}
              onClick={() => onSelectOverlay?.(o.id)}
              onMovePointerDown={(e) =>
                handleOverlayMovePointerDown(e, o)
              }
              onResizePointerDown={(_corner, e) =>
                handleOverlayResizePointerDown(e, o)
              }
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
            />
          ))}

        {/* figma 1669:49437 — element selection action bar (선택 + content + trash) */}
        {(() => {
          const selectedOverlay = overlays.find((o) => o.id === selectedOverlayId);
          const selectedSubtitle =
            selectedSubtitleIndex != null && selectedSubtitleIndex < subtitles.length
              ? subtitles[selectedSubtitleIndex]
              : null;
          if (selectedOverlay && onRemoveOverlay) {
            const label =
              selectedOverlay.kind === "text"
                ? selectedOverlay.text
                : "단색 배경";
            return (
              <div
                className="absolute bottom-4 left-1/2 z-20 -translate-x-1/2"
                onClick={(e) => e.stopPropagation()}
              >
                <SubtitleCancelActionBar
                  text={label}
                  onRemove={() => onRemoveOverlay(selectedOverlay.id)}
                />
              </div>
            );
          }
          if (selectedSubtitle && onRemoveSubtitle && selectedSubtitleIndex != null) {
            return (
              <div
                className="absolute bottom-4 left-1/2 z-20 -translate-x-1/2"
                onClick={(e) => e.stopPropagation()}
              >
                <SubtitleCancelActionBar
                  text={selectedSubtitle.text}
                  onRemove={() => onRemoveSubtitle(selectedSubtitleIndex)}
                />
              </div>
            );
          }
          return null;
        })()}

        {/* No clips placeholder */}
        {clips.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-grayscale-500">
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
          "flex w-full flex-col gap-2 transition-opacity duration-200 max-w-[352px]",
          showTransport ? "opacity-100" : "pointer-events-none opacity-0",
        )}
      >
        {/* Progress bar */}
        <div className="relative h-1 w-full rounded-full bg-grayscale-200">
          <div
            className="absolute left-0 top-0 h-full rounded-full bg-heimdex-navy-500 transition-[width] duration-75"
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
                ? "bg-heimdex-navy-500 text-white hover:bg-heimdex-navy-600"
                : "cursor-not-allowed bg-grayscale-100 text-grayscale-400",
            )}
          >
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>

          <span className="font-mono text-xs text-grayscale-500">
            {formatTimelineTimestamp(playheadMs)} / {formatTimelineTimestamp(totalDurationMs)}
          </span>
        </div>
      </div>
    </div>
  );
}
