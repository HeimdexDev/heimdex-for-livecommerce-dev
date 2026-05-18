"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// figma: 1602:41332 — color palette popover.
//
// Sections (top to bottom):
//   - Header (색상 + close)
//   - 사용 중인 색상 (figma 1602:41339) — rainbow wheel triggers a custom
//     color picker, plus a chip showing the currently selected color.
//   - 기본 색상 (transparent + neutrals + 6×5 tonal grid)
//   - 선택 색상 (hex readout)
//   - 불투명도 slider (optional)
//
// The popover keeps state local for color + opacity and pushes the
// composite (hex + alpha) back to the parent via onChange.

interface ColorPalettePopoverProps {
  color: string;
  opacity?: number;
  onChange: (color: string) => void;
  onOpacityChange?: (opacity: number) => void;
  onClose: () => void;
  showOpacity?: boolean;
}

const BASIC_COLORS = [
  "#000000",
  "#434343",
  "#7B7B7B",
  "#C4C4C4",
  "#E9E9E9",
  "#FFFFFF",
];

const PALETTE_COLUMNS: string[][] = [
  ["#4E2677", "#613095", "#8F40AB", "#B073C3", "#DBC2E5"],
  ["#2F4083", "#3B4FA5", "#5F6FBB", "#A0AAD6", "#CDD3EF"],
  ["#2B6CA2", "#3787CB", "#47A7ED", "#73CAFC", "#C0E8FE"],
  ["#4E6C30", "#61873D", "#88AF53", "#B6D18B", "#E6EFD7"],
  ["#BF6129", "#EF7934", "#F3A33E", "#F9CE5B", "#FCEFC8"],
  ["#A34426", "#CC552F", "#EC613B", "#F1916E", "#F8CEC0"],
];

// figma 1602:41339 — conic-gradient rainbow swatch used as the custom
// color picker entry. Picked to roughly match the figma reference; exact
// stops don't need to match the design system since this is just the
// visual hint that the user can pick any color from here.
const RAINBOW_WHEEL_GRADIENT =
  "conic-gradient(from 90deg, #F9CE5B, #F3A33E, #EC613B, #CC552F, #A34426, #4E2677, #613095, #8F40AB, #5F6FBB, #3B4FA5, #2F4083, #2B6CA2, #3787CB, #47A7ED, #4E6C30, #61873D, #88AF53, #F9CE5B)";

export function ColorPalettePopover({
  color,
  opacity = 1,
  onChange,
  onOpacityChange,
  onClose,
  showOpacity = true,
}: ColorPalettePopoverProps) {
  const [localOpacity, setLocalOpacity] = useState(opacity);
  // Hidden ``<input type="color">`` — clicked via its ref to surface the
  // native picker without a visible chrome input on the card.
  const nativePickerRef = useRef<HTMLInputElement>(null);

  useEffect(() => setLocalOpacity(opacity), [opacity]);

  const handleOpacity = useCallback(
    (value: number) => {
      setLocalOpacity(value);
      onOpacityChange?.(value);
    },
    [onOpacityChange],
  );

  const opacityPct = Math.round(localOpacity * 100);
  const isTransparent = color === "transparent";
  // ``<input type="color">`` requires a 7-char hex; fall back to black
  // when the current value is "transparent" or otherwise unparseable.
  const nativeInitial = /^#([0-9A-F]{6})$/i.test(color) ? color : "#000000";

  return (
    <div
      // figma 1602:41332 — 260×p-[20px] white card, gap-[16px] between sections.
      className="flex w-[260px] flex-col gap-[16px] rounded-[20px] bg-white p-[20px] shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
    >
      <div className="flex items-center justify-between">
        <p className="text-[14px] font-semibold tracking-[-0.35px] text-grayscale-800">
          색상
        </p>
        <button
          type="button"
          onClick={onClose}
          aria-label="팔레트 닫기"
          className="text-grayscale-500 hover:text-grayscale-800"
        >
          <X className="h-5 w-5" strokeWidth={2} />
        </button>
      </div>

      {/* figma 1602:41339 — 사용 중인 색상.
          Rainbow wheel is the custom-picker affordance (triggers the
          hidden native color input). The chip next to it shows the
          color the user just picked so they can spot it without
          scanning the grid. */}
      <div className="flex flex-col gap-[8px]">
        <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          사용 중인 색상
        </p>
        <div className="flex items-center gap-[10px]">
          <button
            type="button"
            onClick={() => nativePickerRef.current?.click()}
            aria-label="사용자 정의 색상 선택"
            className="relative grid h-[30px] w-[30px] place-items-center overflow-hidden rounded-full border border-grayscale-300"
            style={{ background: RAINBOW_WHEEL_GRADIENT }}
          >
            {/* Crosshair / picker icon centered on a white disc. */}
            <span className="grid h-[16px] w-[16px] place-items-center rounded-full bg-white text-grayscale-800">
              <svg viewBox="0 0 16 16" className="h-3 w-3" aria-hidden>
                <circle cx="8" cy="8" r="2" fill="currentColor" />
                <path
                  d="M8 1v3M8 12v3M1 8h3M12 8h3"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </span>
          </button>
          <input
            ref={nativePickerRef}
            type="color"
            value={nativeInitial}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            aria-hidden
            tabIndex={-1}
            className="pointer-events-none absolute h-0 w-0 opacity-0"
          />
          {/* Currently-selected chip — gives the user a "you picked this"
              cue. Renders the transparent diagonal when no color set. */}
          <div
            className={cn(
              "relative h-[30px] w-[30px] overflow-hidden rounded-[6px] border",
              "border-grayscale-300",
            )}
            style={{
              backgroundColor: isTransparent ? "#FFFFFF" : color,
            }}
            aria-label={`선택 색상 ${color}`}
          >
            {isTransparent && (
              <span
                aria-hidden
                className="absolute left-1/2 top-1/2 block h-[2px] w-[41px] -translate-x-1/2 -translate-y-1/2 rotate-[-47deg] bg-red-h-400"
              />
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-[8px]">
        <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          기본 색상
        </p>
        {/* figma 1602:41348 — diagonal line swatch acts as the "no color /
            transparent" pick. Selecting it clears the fill. */}
        <button
          type="button"
          onClick={() => onChange("transparent")}
          aria-label="색상 없음"
          className="relative h-[30px] w-[30px] overflow-hidden rounded-[6px] border border-grayscale-300 bg-white"
        >
          <span
            aria-hidden
            className="absolute left-1/2 top-1/2 block h-[2px] w-[41px] -translate-x-1/2 -translate-y-1/2 rotate-[-47deg] bg-red-h-400"
          />
        </button>
        {/* figma 1602:41350 — neutral row: black/charcoal/gray/silver/light/white */}
        <div className="flex items-center justify-between">
          {BASIC_COLORS.map((c) => (
            <ColorChip key={c} color={c} active={c === color} onClick={() => onChange(c)} />
          ))}
        </div>
        {/* figma 1602:41357 — 6 columns × 5 rows tonal grid. */}
        <div className="flex justify-between gap-[8px]">
          {PALETTE_COLUMNS.map((column, idx) => (
            <div key={idx} className="flex flex-col gap-[10px]">
              {column.map((c) => (
                <ColorChip key={c} color={c} active={c === color} onClick={() => onChange(c)} />
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-[8px]">
        <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          선택 색상
        </p>
        <div className="flex justify-end">
          <div className="flex w-[100px] items-center gap-[10px] rounded-[6px] border border-grayscale-300 p-[5px]">
            <span className="block h-5 w-5 rounded-[4px]" style={{ backgroundColor: color }} />
            <span className="text-[12px] font-medium tracking-[-0.3px] text-black">
              {color.toUpperCase()}
            </span>
          </div>
        </div>
      </div>

      {showOpacity && onOpacityChange && (
        <div className="flex flex-col gap-[8px]">
          <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
            불투명도
          </p>
          <div className="flex items-center justify-between gap-[8px]">
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={localOpacity}
              onChange={(e) => handleOpacity(Number(e.target.value))}
              aria-label={`불투명도 ${opacityPct}%`}
              className="h-[2px] flex-1 cursor-pointer accent-grayscale-800"
            />
            <div className="flex h-10 items-center rounded-[10px] border border-grayscale-300 px-2 py-2.5">
              <span className="text-[14px] font-medium tracking-[-0.35px] text-grayscale-800">
                {opacityPct}%
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ColorChip({
  color,
  active,
  onClick,
}: {
  color: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`색상 ${color}`}
      className={cn(
        "rounded-[6px] border transition-shadow",
        active
          ? "border-[1.333px] border-heimdex-navy-300 p-[2.667px]"
          : "border-grayscale-300",
      )}
    >
      <span
        className="block rounded-[5.333px]"
        style={{ backgroundColor: color, width: active ? 26.667 : 30, height: active ? 26.667 : 30 }}
      />
    </button>
  );
}
