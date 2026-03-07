"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import { getCloudThumbnailUrl } from "@/lib/agent";
import { cn } from "@/lib/utils";
import { PersonTimelineScene } from "@/lib/types/people";

interface TimelineBarProps {
  scenes: PersonTimelineScene[];
  videoId: string;
  videoTitle: string | null;
  onSceneClick: (videoId: string, startMs: number) => void;
}

function formatTime(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function TimelineBarComponent({
  scenes,
  videoId,
  videoTitle,
  onSceneClick,
}: TimelineBarProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [visible, setVisible] = useState(false);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [imgError, setImgError] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const handleMouseEnter = useCallback(
    (index: number) => {
      clearTimer();
      setHoveredIndex(index);
      timerRef.current = setTimeout(() => setVisible(true), 150);
    },
    [clearTimer]
  );

  const handleMouseLeave = useCallback(() => {
    clearTimer();
    setVisible(false);
    setHoveredIndex(null);
  }, [clearTimer]);

  useEffect(() => {
    return clearTimer;
  }, [clearTimer]);

  useEffect(() => {
    setImgLoaded(false);
    setImgError(false);
  }, [hoveredIndex]);

  const hoveredScene = hoveredIndex !== null ? scenes[hoveredIndex] : null;
  const thumbnailUrl =
    hoveredScene && videoId
      ? getCloudThumbnailUrl(videoId, hoveredScene.scene_id)
      : null;

  return (
    <div
      className="relative flex h-1.5 w-full gap-px rounded-full bg-gray-100"
      role="group"
      aria-label={videoTitle ? `${videoTitle} 타임라인` : "타임라인"}
    >
      {scenes.map((scene, i) => (
        <div
          key={scene.scene_id}
          className={cn(
            "h-full flex-1 cursor-pointer first:rounded-l-full last:rounded-r-full transition-colors",
            scene.has_person ? "bg-blue-500 hover:bg-blue-600" : "bg-gray-200 hover:bg-gray-300"
          )}
          onMouseEnter={() => handleMouseEnter(i)}
          onMouseLeave={handleMouseLeave}
          onClick={() => onSceneClick(videoId, scene.start_ms)}
        />
      ))}

      {visible && hoveredIndex !== null && hoveredScene && thumbnailUrl && !imgError && (
        <div
          className="absolute bottom-full z-50 mb-2 -translate-x-1/2 pointer-events-none"
          style={{ left: `${((hoveredIndex + 0.5) / scenes.length) * 100}%` }}
        >
          <div className="rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
            <div className="relative h-[72px] w-[128px] overflow-hidden rounded-md bg-gray-100">
              <img
                src={thumbnailUrl}
                alt={`Scene ${hoveredIndex + 1}`}
                className={cn(
                  "h-full w-full object-cover transition-opacity duration-150",
                  imgLoaded ? "opacity-100" : "opacity-0"
                )}
                onLoad={() => setImgLoaded(true)}
                onError={() => setImgError(true)}
              />
              {!imgLoaded && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
                </div>
              )}
            </div>
            <div className="mt-1 flex items-center justify-center px-0.5">
              <span className="truncate text-[11px] font-medium text-gray-700">
                장면 {hoveredIndex + 1} · {formatTime(hoveredScene.start_ms)}
              </span>
            </div>
          </div>
          <div className="flex justify-center">
            <div className="h-2 w-2 -translate-y-1 rotate-45 border-b border-r border-gray-200 bg-white" />
          </div>
        </div>
      )}
    </div>
  );
}

export const TimelineBar = React.memo(TimelineBarComponent);
