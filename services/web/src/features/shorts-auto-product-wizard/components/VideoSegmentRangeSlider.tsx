// ============================================================================
// Two-handle range slider over a video duration. Replaces the mm:ss text
// inputs in the inline criteria step (legacy ``WizardStepCriteria`` already
// flagged this as a follow-up). Self-contained — no shared timeline state,
// no external dep.
//
// Semantics:
//   * ``startMs === null && endMs === null`` ⇒ user hasn't constrained the
//     range; UI shows handles at the extremes (0 and durationMs) but the
//     onChange payload preserves null so the criteria step submits "no
//     range constraint" (whole video).
//   * Once a handle is dragged or keyboard-nudged, the corresponding side
//     becomes a real number. Resetting both back to null is allowed via
//     the ``onReset`` callback (caller's responsibility — the slider just
//     respects whatever it's told).
//   * Handles maintain ``MIN_SEPARATION_MS`` between them so the criteria
//     step's aggregate-cap warning doesn't trip on a degenerate 0-length
//     range.
// ============================================================================

"use client";

import { useCallback, useRef, useState } from "react";

import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

const MIN_SEPARATION_MS = 1_000; // 1s — keeps the range meaningful
const KEYBOARD_STEP_MS = 1_000; // arrow keys nudge by 1s
const KEYBOARD_STEP_LARGE_MS = 10_000; // shift+arrow nudge by 10s
const DEFAULT_SNAP_RADIUS_MS = 500; // ±0.5s grace zone around scene boundaries

type Handle = "start" | "end";

interface Props {
  durationMs: number;
  startMs: number | null;
  endMs: number | null;
  onChange: (next: { startMs: number | null; endMs: number | null }) => void;
  /**
   * Optional list of timestamps (ms) the handles should snap to when
   * dragged within ``snapRadiusMs``. Pass scene boundaries (start_ms,
   * end_ms of each scene) so the user lands on natural cut points.
   * Empty / undefined disables snap entirely (free dragging).
   */
  snapTargetsMs?: number[];
  /** Snap grace zone in ms. Default 500. Set to 0 to require exact hits. */
  snapRadiusMs?: number;
  disabled?: boolean;
  className?: string;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, value));
}

/**
 * Snap ``ms`` to the nearest target within ``radiusMs``. If no target is
 * within the grace zone (or targets is empty), returns ``ms`` unchanged so
 * the user can still pick arbitrary off-boundary values. Pure — exported
 * for direct unit testability.
 */
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
  const [draggingHandle, setDraggingHandle] = useState<Handle | null>(null);

  // For display + interaction we treat null as "extreme" — but we never
  // synthesize a non-null value into onChange unless the user actually
  // moves the handle. That's why we have effective* (display) and the
  // onChange path stays null-aware.
  const effectiveStart = startMs ?? 0;
  const effectiveEnd = endMs ?? durationMs;

  const startPct = durationMs > 0 ? (effectiveStart / durationMs) * 100 : 0;
  const endPct = durationMs > 0 ? (effectiveEnd / durationMs) * 100 : 100;

  const commit = useCallback(
    (handle: Handle, ms: number) => {
      // Snap BEFORE clamp/separation so that a snap target at the
      // duration boundary is reachable, and BEFORE the min-separation
      // floor/ceiling so a snap target near the other handle still
      // clamps correctly.
      const snapped = snapTargetsMs
        ? snapToNearest(ms, snapTargetsMs, snapRadiusMs)
        : ms;
      const clampedToDuration = clamp(snapped, 0, durationMs);
      if (handle === "start") {
        const ceiling = (endMs ?? durationMs) - MIN_SEPARATION_MS;
        const next = clamp(clampedToDuration, 0, Math.max(0, ceiling));
        onChange({ startMs: next, endMs });
      } else {
        const floor = (startMs ?? 0) + MIN_SEPARATION_MS;
        const next = clamp(clampedToDuration, Math.min(floor, durationMs), durationMs);
        onChange({ startMs, endMs: next });
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

  // Defensive: if durationMs flips to 0 (rare, e.g. a video without scenes),
  // hide the slider. The criteria step should fall back to mm:ss text inputs
  // in that path — caller's responsibility, not ours.
  if (durationMs <= 0) return null;

  return (
    <div
      className={cn("space-y-3", disabled && "opacity-50", className)}
      data-testid="video-segment-range-slider"
    >
      <div
        ref={trackRef}
        className="relative h-1.5 rounded-full bg-gray-200"
        role="group"
        aria-label="영상 구간 범위"
      >
        {/* Filled segment between handles */}
        <div
          className="absolute h-full rounded-full bg-gray-900"
          style={{ left: `${startPct}%`, right: `${100 - endPct}%` }}
        />
        {/* Snap-target tick marks (scene boundaries). Only meaningful when
            durationMs > 0 — when 0, the component already returns null
            above. Filtered to interior boundaries (skip 0 and durationMs)
            so the start/end edges aren't doubled by handle visuals. */}
        {snapTargetsMs && durationMs > 0
          ? snapTargetsMs
              .filter((t) => t > 0 && t < durationMs)
              .map((t, i) => (
                <span
                  key={`snap-${i}-${t}`}
                  className="absolute top-1/2 h-3 w-px -translate-x-1/2 -translate-y-1/2 bg-gray-400"
                  style={{ left: `${(t / durationMs) * 100}%` }}
                  data-testid="range-snap-tick"
                  aria-hidden="true"
                />
              ))
          : null}
        {/* Start handle */}
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
            "absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-gray-900 bg-white shadow",
            "focus:outline-none focus:ring-2 focus:ring-indigo-300",
            disabled && "cursor-not-allowed",
          )}
          style={{ left: `${startPct}%` }}
          data-testid="range-handle-start"
        />
        {/* End handle */}
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
            "absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-gray-900 bg-white shadow",
            "focus:outline-none focus:ring-2 focus:ring-indigo-300",
            disabled && "cursor-not-allowed",
          )}
          style={{ left: `${endPct}%` }}
          data-testid="range-handle-end"
        />
      </div>
      <div className="flex items-center justify-between text-xs text-gray-600">
        <span data-testid="range-label-start">
          {formatVideoTimestampHMS(effectiveStart)}
        </span>
        <span data-testid="range-label-end">
          {formatVideoTimestampHMS(effectiveEnd)}
        </span>
      </div>
    </div>
  );
}
