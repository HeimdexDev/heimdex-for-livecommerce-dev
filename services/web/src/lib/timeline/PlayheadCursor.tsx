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
      className="pointer-events-none absolute top-0 z-30 flex -translate-x-1/2 flex-col items-center"
      style={{ left: leftPx, height }}
    >
      {tooltipVisible && (
        <div
          className="pointer-events-none absolute -top-6 left-1/2 flex -translate-x-1/2 flex-col items-center"
          aria-hidden="true"
        >
          <div className="whitespace-nowrap rounded-md bg-grayscale-800 px-1.5 py-0.5 font-mono text-[10px] leading-none text-white shadow">
            {formatTimelineTimestamp(playheadMs)}
          </div>
          {/* figma asset Polygon 1 — downward arrow under the tooltip */}
          <svg width="10" height="8" viewBox="0 0 10 8" fill="none" className="-mt-px">
            <path d="M5 8L6.99382e-07 -8.74228e-07L10 0L5 8Z" fill="#272833" />
          </svg>
        </div>
      )}
      {/* figma: 1669:48428 — rounded chevron-down pointer (12×10 path) inside
          a 16×16 hit area; sits flush on top of the 2px heimdex-navy bar. */}
      <div
        className="pointer-events-auto flex h-4 w-4 shrink-0 cursor-grab items-center justify-center active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerEnter={() => setIsHovering(true)}
        onPointerLeave={() => setIsHovering(false)}
      >
        <svg width="12" height="10" viewBox="0 0 12 10" fill="none" className="shrink-0">
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M10.6641 0C11.7423 0.000245073 12.3739 1.21401 11.7559 2.09766L7.09179 8.76562C6.56102 9.52428 5.438 9.52428 4.90722 8.76562L0.243159 2.09766C-0.374937 1.214 0.256651 0.000226545 1.33496 0H10.6641Z"
            fill="#234C77"
          />
        </svg>
      </div>
      <div className="w-[2px] shrink-0 bg-heimdex-navy-500" style={{ height: Math.max(0, height - 16) }} />
    </div>
  );
}
