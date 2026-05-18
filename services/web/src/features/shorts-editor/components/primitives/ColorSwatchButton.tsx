"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { ColorPalettePopover } from "./ColorPalettePopover";

interface ColorSwatchButtonProps {
  color: string; // hex, e.g. "#FF0000"
  onChange: (color: string) => void;
  disabled?: boolean;
  ariaLabel: string;
  size?: "sm" | "md";
  className?: string;
}

/**
 * Color swatch button — square showing the current color. Clicking opens the
 * figma 1602:41332 color palette popover. The native browser picker was
 * replaced with this custom popover so the palette matches the design and
 * supports opacity controls.
 */
export function ColorSwatchButton({
  color,
  onChange,
  disabled = false,
  ariaLabel,
  size = "md",
  className,
}: ColorSwatchButtonProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative inline-block">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        className={cn(
          "relative inline-flex cursor-pointer items-center justify-center rounded-lg border border-grayscale-200 bg-white p-0.5",
          size === "sm" ? "h-7 w-7" : "h-9 w-9",
          disabled && "cursor-not-allowed opacity-40",
          className,
        )}
      >
        <span
          className="block h-full w-full rounded"
          style={{ backgroundColor: color }}
        />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-50 mt-2">
          <ColorPalettePopover
            color={color}
            onChange={(next) => {
              onChange(next.toUpperCase());
              setOpen(false);
            }}
            onClose={() => setOpen(false)}
            showOpacity={false}
          />
        </div>
      )}
    </div>
  );
}
