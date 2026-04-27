"use client";

import { useCallback, useRef, useEffect, useState } from "react";
import { msToPixels, pixelsToMs, formatTimelineTimestamp } from "./timeline-math";

interface PlayheadCursorProps {
  playheadMs: number;
  zoom: number;
  height: number;
  onSeek: (ms: number) => void;
  /**
   * Render a small timestamp badge above the playhead handle on hover/drag.
   * Off by default so existing consumers (e.g., blur editor) are unchanged.
   */
  showTooltip?: boolean;
}

export function PlayheadCursor({
  playheadMs,
  zoom,
  height,
  onSeek,
  showTooltip = false,
}: PlayheadCursorProps) {
  const leftPx = msToPixels(playheadMs, zoom);
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startMsRef = useRef(0);
  const [isHovering, setIsHovering] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      if (!draggingRef.current) return;
      const dx = e.clientX - startXRef.current;
      const newMs = Math.max(0, startMsRef.current + pixelsToMs(dx, zoom));
      onSeek(Math.round(newMs));
    },
    [zoom, onSeek],
  );

  const onPointerUp = useCallback(
    (e: PointerEvent) => {
      draggingRef.current = false;
      setIsDragging(false);
      (e.target as HTMLElement)?.releasePointerCapture?.(e.pointerId);
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    },
    [onPointerMove],
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.stopPropagation();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      draggingRef.current = true;
      setIsDragging(true);
      startXRef.current = e.clientX;
      startMsRef.current = playheadMs;
      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    },
    [playheadMs, onPointerMove, onPointerUp],
  );

  useEffect(() => {
    return () => {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    };
  }, [onPointerMove, onPointerUp]);

  const tooltipVisible = showTooltip && (isHovering || isDragging);

  return (
    <div
      className="pointer-events-none absolute top-0 z-30"
      style={{ left: leftPx, height }}
    >
      {tooltipVisible && (
        <div
          className="pointer-events-none absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-gray-900 px-1.5 py-0.5 font-mono text-[10px] leading-none text-white shadow"
          aria-hidden="true"
        >
          {formatTimelineTimestamp(playheadMs)}
        </div>
      )}
      <div
        className="pointer-events-auto relative -left-[5px] cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerEnter={() => setIsHovering(true)}
        onPointerLeave={() => setIsHovering(false)}
      >
        <svg width="11" height="8" viewBox="0 0 11 8" className="fill-red-500">
          <path d="M0 0h11L5.5 8z" />
        </svg>
      </div>
      <div className="w-px bg-red-500" style={{ height: height - 8 }} />
    </div>
  );
}
