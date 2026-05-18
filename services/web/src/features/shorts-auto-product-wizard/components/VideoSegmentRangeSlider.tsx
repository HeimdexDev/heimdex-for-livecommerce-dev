// figma: 1602:36819  (영상 구간 설정 — slider with start/end time boxes + adjust tooltips)
//
// Layout (single row):
//   [start time box] [progress track w/ two handles] [end time box]
//
// Clicking either time box toggles a black adjuster tooltip directly under
// the box with [−] [m:ss] [+] for fine-grained nudging (1s steps). The box
// itself also displays the current value (HH:MM:SS) and adopts a navy
// outline while its tooltip is open.
//
// Semantics:
//   * ``startMs === null && endMs === null`` ⇒ user hasn't constrained the
//     range; UI shows handles at the extremes (0 and durationMs) and the
//     onChange payload also keeps both null so the criteria step submits
//     "no range constraint" (whole video).
//   * Once a handle is dragged or keyboard-nudged, BOTH sides become real
//     numbers in the onChange payload — the unmoved side is backfilled to
//     its effective extreme (start → 0, end → durationMs). The wizard
//     submits to a backend that XOR-validates the pair (both-or-neither),
//     so emitting ``{number, null}`` would 422 the user. Callers can still
//     reset both sides back to null themselves; the slider just refuses to
//     produce the asymmetric shape.
//   * Handles maintain ``MIN_SEPARATION_MS`` between them so the criteria
//     step's aggregate-cap warning doesn't trip on a degenerate 0-length
//     range.

"use client";

import { Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

const MIN_SEPARATION_MS = 1_000;
const KEYBOARD_STEP_MS = 1_000;
const KEYBOARD_STEP_LARGE_MS = 10_000;
const DEFAULT_SNAP_RADIUS_MS = 500;
const TOOLTIP_NUDGE_MS = 1_000;

type Handle = "start" | "end";

interface Props {
  durationMs: number;
  startMs: number | null;
  endMs: number | null;
  onChange: (next: { startMs: number | null; endMs: number | null }) => void;
  snapTargetsMs?: number[];
  snapRadiusMs?: number;
  disabled?: boolean;
  className?: string;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value));
}

function formatMmSs(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function normalizeTimeRangeForSubmit(
  startMs: number | null,
  endMs: number | null,
  durationMs: number,
): { startMs: number | null; endMs: number | null } {
  if (startMs === null && endMs === null) {
    return { startMs: null, endMs: null };
  }
  return { startMs: startMs ?? 0, endMs: endMs ?? durationMs };
}

export function snapToNearest(
  ms: number,
  targets: number[],
  radiusMs: number,
): number {
  if (targets.length === 0 || radiusMs <= 0) return ms;
  let nearest = ms;
  let nearestDelta = Infinity;
  for (const t of targets) {
    const d = Math.abs(t - ms);
    if (d < nearestDelta) {
      nearestDelta = d;
      nearest = t;
    }
  }
  return nearestDelta <= radiusMs ? nearest : ms;
}

export function VideoSegmentRangeSlider({
  durationMs,
  startMs,
  endMs,
  onChange,
  snapTargetsMs,
  snapRadiusMs = DEFAULT_SNAP_RADIUS_MS,
  disabled,
  className,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [draggingHandle, setDraggingHandle] = useState<Handle | null>(null);
  const [openTooltip, setOpenTooltip] = useState<Handle | null>(null);

  const effectiveStart = startMs ?? 0;
  const effectiveEnd = endMs ?? durationMs;

  const startPct = durationMs > 0 ? (effectiveStart / durationMs) * 100 : 0;
  const endPct = durationMs > 0 ? (effectiveEnd / durationMs) * 100 : 100;

  const commit = useCallback(
    (handle: Handle, ms: number) => {
      const snapped = snapTargetsMs
        ? snapToNearest(ms, snapTargetsMs, snapRadiusMs)
        : ms;
      const clampedToDuration = clamp(snapped, 0, durationMs);
      if (handle === "start") {
        const ceiling = (endMs ?? durationMs) - MIN_SEPARATION_MS;
        const next = clamp(clampedToDuration, 0, Math.max(0, ceiling));
        onChange({ startMs: next, endMs: endMs ?? durationMs });
      } else {
        const floor = (startMs ?? 0) + MIN_SEPARATION_MS;
        const next = clamp(clampedToDuration, Math.min(floor, durationMs), durationMs);
        onChange({ startMs: startMs ?? 0, endMs: next });
      }
    },
    [durationMs, endMs, startMs, onChange, snapTargetsMs, snapRadiusMs],
  );

  const handlePointerDown = (handle: Handle) => (e: React.PointerEvent) => {
    if (disabled) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDraggingHandle(handle);
  };

  const handlePointerMove = (handle: Handle) => (e: React.PointerEvent) => {
    if (draggingHandle !== handle) return;
    const track = trackRef.current;
    if (!track) return;
    const rect = track.getBoundingClientRect();
    if (rect.width <= 0) return;
    const ratio = clamp((e.clientX - rect.left) / rect.width, 0, 1);
    commit(handle, Math.round(ratio * durationMs));
  };

  const handlePointerUp = (handle: Handle) => (e: React.PointerEvent) => {
    if (draggingHandle !== handle) return;
    (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    setDraggingHandle(null);
  };

  const handleKeyDown = (handle: Handle) => (e: React.KeyboardEvent) => {
    if (disabled) return;
    const step = e.shiftKey ? KEYBOARD_STEP_LARGE_MS : KEYBOARD_STEP_MS;
    let delta = 0;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") delta = -step;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") delta = step;
    else return;
    e.preventDefault();
    const current = handle === "start" ? effectiveStart : effectiveEnd;
    commit(handle, current + delta);
  };

  const toggleTooltip = (handle: Handle) => {
    if (disabled) return;
    setOpenTooltip((prev) => (prev === handle ? null : handle));
  };

  const nudge = (handle: Handle, deltaMs: number) => {
    const current = handle === "start" ? effectiveStart : effectiveEnd;
    commit(handle, current + deltaMs);
  };

  // Close the open tooltip when the user clicks outside the slider root.
  useEffect(() => {
    if (openTooltip === null) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const root = rootRef.current;
      if (!root) return;
      if (!root.contains(e.target as Node)) setOpenTooltip(null);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [openTooltip]);

  if (durationMs <= 0) return null;

  return (
    <div
      ref={rootRef}
      className={cn("relative font-pretendard", disabled && "opacity-50", className)}
      data-testid="video-segment-range-slider"
    >
      <div className="flex h-[46px] items-center justify-between gap-[8px]">
        <button
          type="button"
          onClick={() => toggleTooltip("start")}
          disabled={disabled}
          className={cn(
            "shrink-0 rounded-[10px] border bg-white px-[10px] py-[6px] text-[14px] font-medium leading-[1.4] tracking-[-0.35px]",
            openTooltip === "start"
              ? "border-heimdex-navy-500 text-heimdex-navy-500"
              : "border-neutral-h-100 text-neutral-h-400",
          )}
          data-testid="range-label-start"
          data-active={openTooltip === "start"}
          aria-expanded={openTooltip === "start"}
        >
          {formatVideoTimestampHMS(effectiveStart)}
        </button>

        <div className="flex flex-1 items-center justify-center gap-[8px] px-[8px] py-[6px]">
          <div
            ref={trackRef}
            className="relative h-[6px] w-full bg-neutral-h-200"
            role="group"
            aria-label="영상 구간 범위"
          >
            <div
              className="absolute h-full bg-heimdex-navy-500"
              style={{ left: `${startPct}%`, right: `${100 - endPct}%` }}
            />
            {snapTargetsMs && durationMs > 0
              ? snapTargetsMs
                  .filter((t) => t > 0 && t < durationMs)
                  .map((t, i) => (
                    <span
                      key={`snap-${i}-${t}`}
                      className="absolute top-1/2 h-3 w-px -translate-x-1/2 -translate-y-1/2 bg-grayscale-400"
                      style={{ left: `${(t / durationMs) * 100}%` }}
                      data-testid="range-snap-tick"
                      aria-hidden="true"
                    />
                  ))
              : null}
            <button
              type="button"
              role="slider"
              aria-label="시작 시간"
              aria-valuemin={0}
              aria-valuemax={durationMs}
              aria-valuenow={effectiveStart}
              aria-valuetext={formatVideoTimestampHMS(effectiveStart)}
              tabIndex={disabled ? -1 : 0}
              disabled={disabled}
              onPointerDown={handlePointerDown("start")}
              onPointerMove={handlePointerMove("start")}
              onPointerUp={handlePointerUp("start")}
              onPointerCancel={handlePointerUp("start")}
              onKeyDown={handleKeyDown("start")}
              className={cn(
                "absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-heimdex-navy-500",
                "focus:outline-none focus:ring-2 focus:ring-heimdex-navy-300",
                disabled && "cursor-not-allowed",
              )}
              style={{ left: `${startPct}%` }}
              data-testid="range-handle-start"
            />
            <button
              type="button"
              role="slider"
              aria-label="종료 시간"
              aria-valuemin={0}
              aria-valuemax={durationMs}
              aria-valuenow={effectiveEnd}
              aria-valuetext={formatVideoTimestampHMS(effectiveEnd)}
              tabIndex={disabled ? -1 : 0}
              disabled={disabled}
              onPointerDown={handlePointerDown("end")}
              onPointerMove={handlePointerMove("end")}
              onPointerUp={handlePointerUp("end")}
              onPointerCancel={handlePointerUp("end")}
              onKeyDown={handleKeyDown("end")}
              className={cn(
                "absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-heimdex-navy-500",
                "focus:outline-none focus:ring-2 focus:ring-heimdex-navy-300",
                disabled && "cursor-not-allowed",
              )}
              style={{ left: `${endPct}%` }}
              data-testid="range-handle-end"
            />
          </div>
        </div>

        <button
          type="button"
          onClick={() => toggleTooltip("end")}
          disabled={disabled}
          className={cn(
            "shrink-0 rounded-[10px] border bg-white px-[10px] py-[6px] text-[14px] font-medium leading-[1.4] tracking-[-0.35px]",
            openTooltip === "end"
              ? "border-heimdex-navy-500 text-heimdex-navy-500"
              : "border-neutral-h-100 text-neutral-h-400",
          )}
          data-testid="range-label-end"
          data-active={openTooltip === "end"}
          aria-expanded={openTooltip === "end"}
        >
          {formatVideoTimestampHMS(effectiveEnd)}
        </button>
      </div>

      {openTooltip ? (
        <RangeAdjustTooltip
          align={openTooltip}
          value={openTooltip === "start" ? effectiveStart : effectiveEnd}
          onDecrement={() => nudge(openTooltip, -TOOLTIP_NUDGE_MS)}
          onIncrement={() => nudge(openTooltip, TOOLTIP_NUDGE_MS)}
        />
      ) : null}
    </div>
  );
}

interface TooltipProps {
  align: Handle;
  value: number;
  onDecrement: () => void;
  onIncrement: () => void;
}

function RangeAdjustTooltip({ align, value, onDecrement, onIncrement }: TooltipProps) {
  return (
    <div
      className={cn(
        "absolute top-full mt-[5px] flex items-center justify-center gap-[4px] rounded-[6px] bg-grayscale-700 p-[8px]",
        align === "start" ? "left-0" : "right-0",
      )}
      role="tooltip"
      data-testid={`range-tooltip-${align}`}
    >
      <span
        className="absolute -top-[8px] h-[8px] w-[10px] -translate-x-1/2"
        style={{ left: "50%" }}
        aria-hidden="true"
      >
        <span className="absolute inset-x-0 top-0 border-x-[5px] border-b-[8px] border-x-transparent border-b-grayscale-700" />
      </span>
      <button
        type="button"
        onClick={onDecrement}
        className="flex h-[16px] w-[16px] items-center justify-center text-white"
        aria-label="시간 감소"
        data-testid={`range-tooltip-${align}-minus`}
      >
        <Minus className="h-[16px] w-[16px]" strokeWidth={2} />
      </button>
      <span className="text-[16px] font-normal leading-none text-white">
        {formatMmSs(value)}
      </span>
      <button
        type="button"
        onClick={onIncrement}
        className="flex h-[16px] w-[16px] items-center justify-center text-white"
        aria-label="시간 증가"
        data-testid={`range-tooltip-${align}-plus`}
      >
        <Plus className="h-[16px] w-[16px]" strokeWidth={2} />
      </button>
    </div>
  );
}
