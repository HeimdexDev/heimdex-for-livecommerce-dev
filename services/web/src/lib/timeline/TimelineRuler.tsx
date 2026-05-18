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

// figma reference uses 12s as the default landing extent; short clips
// should still show a "1s ㆍㆍㆍㆍ 2s ㆍㆍㆍㆍ … 12s ㆍㆍㆍ" baseline so the
// ruler doesn't collapse when totalDurationMs is small or zero. Zooming
// in/out only changes how many seconds the visible width covers — the
// label cadence (1s per major mark) stays constant at zoom ≥ 100.
const RULER_MIN_EXTENT_MS = 12_000;

export function TimelineRuler({ totalDurationMs, zoom }: TimelineRulerProps) {
  const endMs = Math.max(totalDurationMs + 2000, RULER_MIN_EXTENT_MS);

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
    for (let ms = 0; ms <= endMs; ms += intervalMs) {
      result.push({
        ms,
        px: msToPixels(ms, zoom),
        label: formatRulerLabel(ms),
        isMajor: true,
      });
    }

    return result;
  }, [endMs, zoom]);

  const totalWidth = msToPixels(endMs, zoom);

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
              className="absolute inset-y-0 flex items-center whitespace-nowrap text-[12px] font-medium leading-none tracking-[-0.3px] text-grayscale-800"
              style={{ left: mark.px }}
            >
              {mark.label}
            </span>
            {dots.map((x, j) => (
              <span
                key={`${mark.ms}-${j}`}
                className="absolute top-1/2 -translate-y-1/2 block h-[2px] w-[2px] rounded-full bg-grayscale-800"
                style={{ left: x }}
                aria-hidden="true"
              />
            ))}
          </span>
        );
      })}
    </div>
  );
}
