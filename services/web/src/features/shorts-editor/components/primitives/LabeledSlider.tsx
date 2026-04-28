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
 * Domain-agnostic; compose it with onChange transforms for opacity (0-1) or
 * blur (0-200) or anything else.
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

  return (
    <div className={cn("flex items-center gap-2", className)} aria-label={ariaLabel}>
      <button
        type="button"
        onClick={() => onChange(Math.max(min, value - step))}
        disabled={disabled || value <= min}
        className="text-gray-400 transition-colors hover:text-gray-700 disabled:cursor-not-allowed disabled:text-gray-200"
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
        className="flex-1 accent-indigo-500 disabled:cursor-not-allowed"
      />
      <button
        type="button"
        onClick={() => onChange(Math.min(max, value + step))}
        disabled={disabled || value >= max}
        className="text-gray-400 transition-colors hover:text-gray-700 disabled:cursor-not-allowed disabled:text-gray-200"
        aria-label="증가"
      >
        +
      </button>
      <span className="min-w-[3.5rem] rounded-lg border border-gray-200 px-2 py-1 text-center text-xs text-gray-700">
        {readout}
      </span>
    </div>
  );
}
