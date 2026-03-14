"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { getCloudThumbnailUrl } from "@/lib/agent";
import { cn } from "@/lib/utils";

interface ScenePreviewTooltipProps {
  videoId: string | null;
  sceneId: string | null;
  label?: string | null;
  badge?: string;
  /** Delay in ms before showing tooltip (default: 200) */
  delayMs?: number;
  /** Suppress tooltip display (e.g. during drag) */
  disabled?: boolean;
  children: React.ReactNode;
  className?: string;
}

const TOOLTIP_MAX_W = 160;
const TOOLTIP_MAX_H = 220;
const TOOLTIP_DEFAULT_H = 90;

export function ScenePreviewTooltip({
  videoId,
  sceneId,
  label,
  badge,
  delayMs = 200,
  disabled = false,
  children,
  className,
}: ScenePreviewTooltipProps) {
  const [visible, setVisible] = useState(false);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);
  const [thumbSize, setThumbSize] = useState<{ w: number; h: number }>({
    w: TOOLTIP_MAX_W,
    h: TOOLTIP_DEFAULT_H,
  });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const hasThumbnail = !!videoId && !!sceneId;
  const thumbnailUrl = hasThumbnail
    ? getCloudThumbnailUrl(videoId, sceneId)
    : null;

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const handleMouseEnter = useCallback(() => {
    if (disabled || !hasThumbnail) return;
    clearTimer();
    timerRef.current = setTimeout(() => setVisible(true), delayMs);
  }, [disabled, hasThumbnail, delayMs, clearTimer]);

  const handleMouseLeave = useCallback(() => {
    clearTimer();
    setVisible(false);
  }, [clearTimer]);

  const handlePointerDown = useCallback(() => {
    clearTimer();
    setVisible(false);
  }, [clearTimer]);

  const handleImgLoad = useCallback(
    (e: React.SyntheticEvent<HTMLImageElement>) => {
      const { naturalWidth, naturalHeight } = e.currentTarget;
      if (naturalWidth > 0 && naturalHeight > 0) {
        const ratio = naturalWidth / naturalHeight;
        let w = TOOLTIP_MAX_W;
        let h = Math.round(w / ratio);
        if (h > TOOLTIP_MAX_H) {
          h = TOOLTIP_MAX_H;
          w = Math.round(h * ratio);
        }
        setThumbSize({ w, h });
      }
      setImgLoaded(true);
    },
    [],
  );

  useEffect(() => {
    return clearTimer;
  }, [clearTimer]);

  // Reset image state when scene changes
  useEffect(() => {
    setImgLoaded(false);
    setImgError(false);
    setThumbSize({ w: TOOLTIP_MAX_W, h: TOOLTIP_DEFAULT_H });
  }, [videoId, sceneId]);

  return (
    <div
      ref={containerRef}
      className={cn("relative", className)}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onPointerDown={handlePointerDown}
    >
      {children}
      {visible && thumbnailUrl && !imgError && (
        <div className="absolute bottom-full left-1/2 z-50 mb-2 -translate-x-1/2 pointer-events-none">
          <div className="rounded-lg border border-gray-200 bg-white p-1.5 shadow-xl">
            <div
              className="relative overflow-hidden rounded-md bg-gray-100 transition-[width,height] duration-150"
              style={{ width: thumbSize.w, height: thumbSize.h }}
            >
              <img
                src={thumbnailUrl}
                alt={label ?? ""}
                className={cn(
                  "h-full w-full object-contain transition-opacity duration-150",
                  imgLoaded ? "opacity-100" : "opacity-0",
                )}
                onLoad={handleImgLoad}
                onError={() => setImgError(true)}
              />
              {!imgLoaded && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
                </div>
              )}
            </div>
            {(label || badge) && (
              <div className="mt-1 flex items-center gap-1.5 px-0.5">
                {label && (
                  <span className="max-w-[140px] truncate text-[11px] font-medium text-gray-700">
                    {label}
                  </span>
                )}
                {badge && (
                  <span className="flex-shrink-0 rounded-full bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                    {badge}
                  </span>
                )}
              </div>
            )}
          </div>
          <div className="flex justify-center">
            <div className="h-2 w-2 -translate-y-1 rotate-45 border-b border-r border-gray-200 bg-white" />
          </div>
        </div>
      )}
    </div>
  );
}
