"use client";

import { cn } from "@/lib/utils";

interface NumericStepperProps {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string; // e.g. "px", "pt", "°"
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Stepper input: [-] [value unit] [+]. Reusable; knows nothing about overlays.
 *
 * Clicking +/- nudges by `step`. Typing into the input commits on blur or
 * Enter. Values outside [min, max] are clamped before propagating, so
 * callers don't need defensive clamping.
 */
export function NumericStepper({
  value,
  onChange,
  min = -Infinity,
  max = Infinity,
  step = 1,
  unit,
  ariaLabel,
  disabled = false,
  className,
}: NumericStepperProps) {
  const clamp = (v: number) => Math.min(max, Math.max(min, v));

  return (
    <div
      className={cn(
        "flex items-center rounded-lg border border-grayscale-200 bg-white",
        disabled && "opacity-60",
        className,
      )}
      aria-label={ariaLabel}
    >
      <button
        type="button"
        onClick={() => onChange(clamp(value - step))}
        disabled={disabled || value <= min}
        className="flex h-8 w-8 items-center justify-center text-grayscale-500 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-300"
        aria-label="감소"
      >
        −
      </button>
      <input
        type="text"
        inputMode="decimal"
        value={Number.isFinite(value) ? String(value) : ""}
        onChange={(e) => {
          const raw = e.target.value.trim();
          const next = raw === "" ? min : Number(raw);
          if (!Number.isFinite(next)) return;
          onChange(clamp(next));
        }}
        disabled={disabled}
        className="w-full min-w-0 border-x border-transparent bg-transparent py-1 text-center text-sm text-grayscale-800 focus:border-heimdex-navy-400 focus:outline-none disabled:cursor-not-allowed"
      />
      {unit && (
        <span className="px-1 text-[10px] text-grayscale-400 select-none">{unit}</span>
      )}
      <button
        type="button"
        onClick={() => onChange(clamp(value + step))}
        disabled={disabled || value >= max}
        className="flex h-8 w-8 items-center justify-center text-grayscale-500 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-300"
        aria-label="증가"
      >
        +
      </button>
    </div>
  );
}
