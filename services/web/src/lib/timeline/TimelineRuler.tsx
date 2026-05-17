"use client";

import { useMemo } from "react";
import { msToPixels } from "./timeline-math";
import type { TimelineMark } from "./types";

interface TimelineRulerProps {
  totalDurationMs: number;
  zoom: number;
}

// figma: 1669:49089 — "0s, 10s, ..., 1m, 1:10" style labels with a 2px line
// (Frame 1707484546) between each, and a Ellipse 12 dot cluster decorating
// the tail of the ruler.
function formatRulerLabel(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (s === 0) return `${m}m`;
  return `${m}:${String(s).padStart(2, "0")}`;
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
        label: isMajor ? formatRulerLabel(ms) : "",
        isMajor,
      });
    }

    return result;
  }, [totalDurationMs, zoom]);

  const totalWidth = msToPixels(totalDurationMs + 2000, zoom);

  return (
    <div
      className="relative h-6 select-none border-b border-grayscale-100 bg-white"
      style={{ width: totalWidth }}
    >
      {marks.map((mark) => (
        <div key={mark.ms} className="absolute top-0" style={{ left: mark.px }}>
          <div
            className={mark.isMajor ? "h-3 w-px bg-grayscale-300" : "h-2 w-px bg-grayscale-200"}
          />
          {mark.label && (
            <span className="absolute left-1 top-3 whitespace-nowrap text-[12px] font-medium leading-none tracking-[-0.3px] text-grayscale-800">
              {mark.label}
            </span>
          )}
        </div>
      ))}
      {/* figma asset Ellipse 12 ×4 — tail-end ellipsis decoration */}
      <div
        className="absolute top-1 flex items-center gap-4"
        style={{ left: Math.max(0, totalWidth - 56) }}
        aria-hidden="true"
      >
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="block h-[2px] w-[2px] rounded-full bg-grayscale-800"
          />
        ))}
      </div>
    </div>
  );
}
