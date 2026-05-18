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
        // right-0 anchor 으로 변경 — 트리거가 우측 wrapper 안쪽의 우측에 위치할 때
        // 좌상단 기준이면 팔레트 (260px) 가 wrapper 우측을 넘쳐 가로 스크롤이 생긴다.
        // 우측 기준으로 펼치면 트리거 위치와 상관없이 wrapper 안쪽으로 확장된다.
        <div className="absolute right-0 top-full z-50 mt-2">
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
