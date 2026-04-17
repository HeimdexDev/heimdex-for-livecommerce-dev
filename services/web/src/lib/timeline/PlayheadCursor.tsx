"use client";

import { useCallback, useRef, useEffect } from "react";
import { msToPixels, pixelsToMs } from "./timeline-math";

interface PlayheadCursorProps {
  playheadMs: number;
  zoom: number;
  height: number;
  onSeek: (ms: number) => void;
}

export function PlayheadCursor({ playheadMs, zoom, height, onSeek }: PlayheadCursorProps) {
  const leftPx = msToPixels(playheadMs, zoom);
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startMsRef = useRef(0);

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

  return (
    <div
      className="absolute top-0 z-30 pointer-events-none"
      style={{ left: leftPx, height }}
    >
      <div
        className="pointer-events-auto relative -left-[5px] cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDown}
      >
        <svg width="11" height="8" viewBox="0 0 11 8" className="fill-red-500">
          <path d="M0 0h11L5.5 8z" />
        </svg>
      </div>
      <div className="w-px bg-red-500" style={{ height: height - 8 }} />
    </div>
  );
}
