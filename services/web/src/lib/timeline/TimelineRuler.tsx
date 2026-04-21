"use client";

import { useMemo } from "react";
import { msToPixels, formatTimelineTimestamp } from "./timeline-math";
import type { TimelineMark } from "./types";

interface TimelineRulerProps {
  totalDurationMs: number;
  zoom: number;
}

export function TimelineRuler({ totalDurationMs, zoom }: TimelineRulerProps) {
  const marks = useMemo(() => {
    let intervalMs: number;
    if (zoom >= 200) {
      intervalMs = 500;
    } else if (zoom >= 100) {
      intervalMs = 1000;
    } else if (zoom >= 50) {
      intervalMs = 2000;
    } else {
      intervalMs = 5000;
    }

    const result: TimelineMark[] = [];
    const endMs = totalDurationMs + 2000;

    for (let ms = 0; ms <= endMs; ms += intervalMs) {
      const isMajor = ms % (intervalMs * 2) === 0 || intervalMs >= 2000;
      result.push({
        ms,
        px: msToPixels(ms, zoom),
        label: isMajor ? formatTimelineTimestamp(ms) : "",
        isMajor,
      });
    }

    return result;
  }, [totalDurationMs, zoom]);

  const totalWidth = msToPixels(totalDurationMs + 2000, zoom);

  return (
    <div className="relative h-6 border-b border-gray-300 bg-gray-100 select-none" style={{ width: totalWidth }}>
      {marks.map((mark) => (
        <div
          key={mark.ms}
          className="absolute top-0"
          style={{ left: mark.px }}
        >
          <div
            className={mark.isMajor ? "h-3 w-px bg-gray-400" : "h-2 w-px bg-gray-300"}
          />
          {mark.label && (
            <span className="absolute left-0.5 top-3 text-[9px] leading-none text-gray-500 whitespace-nowrap">
              {mark.label}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
