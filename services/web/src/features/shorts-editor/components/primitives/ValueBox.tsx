"use client";

import { cn } from "@/lib/utils";

interface ValueBoxProps {
  value: number;
  onChange?: (next: number) => void;
  prefix?: string;
  suffix?: string;
  min?: number;
  max?: number;
  className?: string;
  ariaLabel?: string;
}

/**
 * Compact numeric display box without +/- stepper buttons.
 *
 * Used for the 2026-05-18 redesigned 변형 / 회전 / 크기 sub-controls in the
 * editor right wrapper, where the operator drags the overlay on the
 * preview canvas to change position, and the box just mirrors the
 * current value. When ``onChange`` is supplied the box stays editable
 * (typing replaces the value); when omitted it renders read-only.
 */
export function ValueBox({
  value,
  onChange,
  prefix,
  suffix,
  min,
  max,
  className,
  ariaLabel,
}: ValueBoxProps) {
  return (
    <div
      className={cn(
        "flex h-9 items-center justify-center gap-1 rounded-lg border border-grayscale-200 bg-white px-2",
        className,
      )}
    >
      {prefix ? (
        <span className="text-[10px] font-medium text-grayscale-400">{prefix}</span>
      ) : null}
      <input
        type="text"
        inputMode="numeric"
        readOnly={!onChange}
        value={String(value)}
        onChange={(e) => {
          if (!onChange) return;
          const raw = Number(e.target.value);
          if (!Number.isFinite(raw)) return;
          let next = raw;
          if (min != null) next = Math.max(min, next);
          if (max != null) next = Math.min(max, next);
          onChange(next);
        }}
        aria-label={ariaLabel}
        className="w-full min-w-0 border-0 bg-transparent p-0 text-center text-sm text-grayscale-800 focus:outline-none"
      />
      {suffix ? (
        <span className="text-[10px] font-medium text-grayscale-400">{suffix}</span>
      ) : null}
    </div>
  );
}

interface ValueBoxXYProps {
  x: number;
  y: number;
  onChangeX?: (next: number) => void;
  onChangeY?: (next: number) => void;
  min?: number;
  max?: number;
  className?: string;
  ariaLabel?: string;
}

/**
 * Combined X / Y value box — single rounded container with the two
 * numbers labelled inline, so the 위치 sub-control of the shadow
 * section reads as ``|X 0 Y 99|`` rather than two separate steppers.
 * Mirrors the figma redesign 2026-05-18 spec.
 */
export function ValueBoxXY({
  x,
  y,
  onChangeX,
  onChangeY,
  min,
  max,
  className,
  ariaLabel,
}: ValueBoxXYProps) {
  return (
    <div
      className={cn(
        "flex h-9 items-center justify-center gap-1.5 rounded-lg border border-grayscale-200 bg-white px-2",
        className,
      )}
      aria-label={ariaLabel}
    >
      <span className="text-[10px] font-medium text-grayscale-400">X</span>
      <ValueInput value={x} onChange={onChangeX} min={min} max={max} ariaLabel={`${ariaLabel ?? ""} X`} />
      <span className="ml-1 text-[10px] font-medium text-grayscale-400">Y</span>
      <ValueInput value={y} onChange={onChangeY} min={min} max={max} ariaLabel={`${ariaLabel ?? ""} Y`} />
    </div>
  );
}

interface ValueBoxWHProps {
  width: number;
  height: number;
  onChangeWidth?: (next: number) => void;
  onChangeHeight?: (next: number) => void;
  unit?: string;
  min?: number;
  max?: number;
  className?: string;
  ariaLabel?: string;
}

/**
 * Combined W / H value box — used for the 크기 sub-control of the
 * background overlay's 변형 section. Reads as
 * ``|W 0px H 999px|`` per the figma redesign.
 */
export function ValueBoxWH({
  width,
  height,
  onChangeWidth,
  onChangeHeight,
  unit = "px",
  min,
  max,
  className,
  ariaLabel,
}: ValueBoxWHProps) {
  return (
    <div
      className={cn(
        "flex h-9 items-center justify-center gap-1.5 rounded-lg border border-grayscale-200 bg-white px-2",
        className,
      )}
      aria-label={ariaLabel}
    >
      <span className="text-[10px] font-medium text-grayscale-400">W</span>
      <ValueInput value={width} onChange={onChangeWidth} min={min} max={max} ariaLabel={`${ariaLabel ?? ""} width`} />
      <span className="text-[10px] font-medium text-grayscale-400">{unit}</span>
      <span className="ml-1 text-[10px] font-medium text-grayscale-400">H</span>
      <ValueInput value={height} onChange={onChangeHeight} min={min} max={max} ariaLabel={`${ariaLabel ?? ""} height`} />
      <span className="text-[10px] font-medium text-grayscale-400">{unit}</span>
    </div>
  );
}

function ValueInput({
  value,
  onChange,
  min,
  max,
  ariaLabel,
}: {
  value: number;
  onChange?: (next: number) => void;
  min?: number;
  max?: number;
  ariaLabel?: string;
}) {
  return (
    <input
      type="text"
      inputMode="numeric"
      readOnly={!onChange}
      value={String(value)}
      onChange={(e) => {
        if (!onChange) return;
        const raw = Number(e.target.value);
        if (!Number.isFinite(raw)) return;
        let next = raw;
        if (min != null) next = Math.max(min, next);
        if (max != null) next = Math.min(max, next);
        onChange(next);
      }}
      aria-label={ariaLabel}
      className="w-7 border-0 bg-transparent p-0 text-center text-sm text-grayscale-800 focus:outline-none"
    />
  );
}
