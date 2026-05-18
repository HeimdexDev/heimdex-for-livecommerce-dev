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
    // figma 1663:45782 — Accordion-style stepper: rounded-10 border
    // grayscale/300, minus/plus icons flank the centered value+unit.
    <div
      className={cn(
        "flex h-9 items-center rounded-[10px] border border-grayscale-300 bg-white",
        disabled && "opacity-60",
        className,
      )}
      aria-label={ariaLabel}
    >
      <button
        type="button"
        onClick={() => onChange(clamp(value - step))}
        disabled={disabled || value <= min}
        className="flex h-full w-8 items-center justify-center text-grayscale-500 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-300"
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
        className="w-full min-w-0 border-x border-transparent bg-transparent py-1 text-center text-[14px] tracking-[-0.35px] text-grayscale-800 focus:border-heimdex-navy-400 focus:outline-none disabled:cursor-not-allowed"
      />
      {unit && (
        <span className="select-none px-1 text-[12px] text-grayscale-500">{unit}</span>
      )}
      <button
        type="button"
        onClick={() => onChange(clamp(value + step))}
        disabled={disabled || value >= max}
        className="flex h-full w-8 items-center justify-center text-grayscale-500 transition-colors hover:text-grayscale-800 disabled:cursor-not-allowed disabled:text-grayscale-300"
        aria-label="증가"
      >
        +
      </button>
    </div>
  );
}
