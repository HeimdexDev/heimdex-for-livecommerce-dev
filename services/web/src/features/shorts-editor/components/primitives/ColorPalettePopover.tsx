"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// figma: 1602:41332 — color palette popover.
// Header (색상 + close), a basic-color grid, an "in use" swatch, the
// currently selected color readout, and an opacity slider.
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

export function ColorPalettePopover({
  color,
  opacity = 1,
  onChange,
  onOpacityChange,
  onClose,
  showOpacity = true,
}: ColorPalettePopoverProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [localOpacity, setLocalOpacity] = useState(opacity);

  useEffect(() => setLocalOpacity(opacity), [opacity]);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  const handleOpacity = useCallback(
    (value: number) => {
      setLocalOpacity(value);
      onOpacityChange?.(value);
    },
    [onOpacityChange],
  );

  const opacityPct = Math.round(localOpacity * 100);

  return (
    <div
      ref={ref}
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

      <div className="flex flex-col gap-[8px]">
        <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          기본 색상
        </p>
        {/* figma 1602:41348 — diagonal line swatch acts as the "no color /
            transparent" pick. Selecting it clears the fill. Kept as the
            first chip so it never reflows when the grid below changes. */}
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
        {/* figma 1602:41357 — 6 columns × 5 rows tonal grid (purple, blue,
            cyan, green, orange, red). PALETTE_COLUMNS is column-major so
            each inner array stacks vertically. */}
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
        {/* figma 1602:41396 — 100px-wide chip aligned to the right side of
            the section, swatch + hex pair. Aligned right per figma so the
            section header has clear left-aligned label whitespace. */}
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
            {/* figma 1602:41412 — accordion-style readout box (46×40, r-10). */}
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
        // figma 1602:41344 — selected chip nests a smaller swatch inside a
        // 32×32 ring to make the active state obvious.
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
