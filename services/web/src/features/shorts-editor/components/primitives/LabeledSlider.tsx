"use client";

import { cn } from "@/lib/utils";

interface LabeledSliderProps {
  value: number; // current value (in domain units, not %)
  onChange: (next: number) => void;
  min: number;
  max: number;
  step?: number;
  formatReadout?: (v: number) => string;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}

/**
 * Slider with — / + iconography flanking the track and an inline readout.
 *
 * Track + thumb sized to the 2026-05-18 figma redesign: 2px track and an
 * 8×8 round thumb. Native `<input type=range>` doesn't expose a "filled
 * portion" pseudo-element across browsers, so we paint the navy-up-to-thumb
 * fill via a CSS gradient computed from `value / (max - min)`.
 */
export function LabeledSlider({
  value,
  onChange,
  min,
  max,
  step = 1,
  formatReadout,
  disabled = false,
  ariaLabel,
  className,
}: LabeledSliderProps) {
  const readout = formatReadout
    ? formatReadout(value)
    : String(Math.round(value));

  const pct = max > min ? Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100)) : 0;
  // Inline gradient so the filled portion (left of thumb) shows in navy and
  // the remainder shows in light gray — matches the figma redesign without
  // browser-specific pseudo-element CSS.
  const trackBg = `linear-gradient(to right, var(--heimdex-navy-500, #1f3a5f) 0%, var(--heimdex-navy-500, #1f3a5f) ${pct}%, var(--grayscale-200, #e5e7eb) ${pct}%, var(--grayscale-200, #e5e7eb) 100%)`;

  return (
    <div className={cn("flex items-center gap-2", className)} aria-label={ariaLabel}>
      <button
        type="button"
        onClick={() => onChange(Math.max(min, value - step))}
        disabled={disabled || value <= min}
        className="text-grayscale-400 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-200"
        aria-label="감소"
      >
        −
      </button>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        style={{ background: trackBg }}
        className={cn(
          "h-[2px] flex-1 cursor-pointer appearance-none rounded-full bg-grayscale-200 disabled:cursor-not-allowed",
          "[&::-webkit-slider-runnable-track]:h-[2px] [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-transparent",
          "[&::-moz-range-track]:h-[2px] [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-transparent",
          "[&::-webkit-slider-thumb]:size-2 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-heimdex-navy-500 [&::-webkit-slider-thumb]:-mt-[3px]",
          "[&::-moz-range-thumb]:size-2 [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-heimdex-navy-500",
        )}
      />
      <button
        type="button"
        onClick={() => onChange(Math.min(max, value + step))}
        disabled={disabled || value >= max}
        className="text-grayscale-400 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-200"
        aria-label="증가"
      >
        +
      </button>
      <span className="min-w-[3.5rem] rounded-lg border border-grayscale-200 px-2 py-1 text-center text-xs text-grayscale-500">
        {readout}
      </span>
    </div>
  );
}
