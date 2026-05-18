"use client";

import { useMemo } from "react";
import { msToPixels } from "./timeline-math";
import type { TimelineMark } from "./types";

interface TimelineRulerProps {
  totalDurationMs: number;
  zoom: number;
}

// figma: 1669:49089 — "0s ㆍㆍㆍㆍ 1s ㆍㆍㆍㆍ 2s ㆍ··" pattern. Every
// interval gets a numeric label; between each pair of labels we draw 4
// small dots (Ellipse 12/13/14/15 in the figma export). Only the
// numbers change as zoom widens, the dot density between labels stays
// the same.
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
    if (zoom >= 100) {
      intervalMs = 1000;
    } else if (zoom >= 50) {
      intervalMs = 2000;
    } else if (zoom >= 25) {
      intervalMs = 5000;
    } else {
      intervalMs = 10000;
    }

    const result: TimelineMark[] = [];
    const endMs = totalDurationMs + 2000;

    for (let ms = 0; ms <= endMs; ms += intervalMs) {
      result.push({
        ms,
        px: msToPixels(ms, zoom),
        label: formatRulerLabel(ms),
        isMajor: true,
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
      {marks.map((mark, idx) => {
        const next = marks[idx + 1];
        const dots: number[] = [];
        if (next) {
          const segment = next.px - mark.px;
          // figma 1707484544 — 4 evenly-distributed dots between labels.
          for (let j = 1; j <= 4; j++) {
            dots.push(mark.px + (segment * j) / 5);
          }
        }
        return (
          <span key={mark.ms}>
            <span
              className="absolute top-[6px] whitespace-nowrap text-[12px] font-medium leading-none tracking-[-0.3px] text-grayscale-800"
              style={{ left: mark.px, transform: "translateX(0)" }}
            >
              {mark.label}
            </span>
            {dots.map((x, j) => (
              <span
                key={`${mark.ms}-${j}`}
                className="absolute block h-[2px] w-[2px] rounded-full bg-grayscale-800"
                style={{ left: x, top: 11 }}
                aria-hidden="true"
              />
            ))}
          </span>
        );
      })}
    </div>
  );
}
