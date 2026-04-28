"use client";

import { cn } from "@/lib/utils";

interface ColorSwatchButtonProps {
  color: string; // hex, e.g. "#FF0000"
  onChange: (color: string) => void;
  disabled?: boolean;
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Color swatch button — a square showing the current color, clicking opens
 * the OS native color picker. Wraps `<input type="color">` so the visual
 * stays consistent with the design system.
 *
 * The native picker has UX limitations (no recent colors, no opacity), but
 * it ships free and the redesign doesn't call out a custom picker. Swap
 * later if needed; the prop surface stays the same.
 */
export function ColorSwatchButton({
  color,
  onChange,
  disabled = false,
  ariaLabel,
  size = "md",
  className,
}: ColorSwatchButtonProps) {
  return (
    <label
      className={cn(
        "relative inline-flex cursor-pointer items-center justify-center rounded-lg border border-gray-200 bg-white p-0.5",
        size === "sm" ? "h-7 w-7" : "h-9 w-9",
        disabled && "cursor-not-allowed opacity-40",
        className,
      )}
      aria-label={ariaLabel}
    >
      <span
        className={cn(
          "block h-full w-full rounded",
        )}
        style={{ backgroundColor: color }}
      />
      <input
        type="color"
        value={color}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        disabled={disabled}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
      />
    </label>
  );
}
