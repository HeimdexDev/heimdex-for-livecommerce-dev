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
      className="flex w-[240px] flex-col gap-4 rounded-[20px] bg-white p-5 shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
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

      <div className="flex flex-col gap-2">
        <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          기본 색상
        </p>
        <div className="flex items-center justify-between">
          {BASIC_COLORS.map((c) => (
            <ColorChip key={c} color={c} active={c === color} onClick={() => onChange(c)} />
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2.5">
        {PALETTE_COLUMNS.map((column, idx) => (
          <div key={idx} className="flex items-center justify-between">
            {column.map((c) => (
              <ColorChip key={c} color={c} active={c === color} onClick={() => onChange(c)} />
            ))}
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          선택 색상
        </p>
        <div className="flex items-center gap-2.5 rounded-[6px] border border-grayscale-300 p-[5px]">
          <span className="block h-5 w-5 rounded-[4px]" style={{ backgroundColor: color }} />
          <span className="text-[12px] font-medium tracking-[-0.3px] text-black">
            {color.toUpperCase()}
          </span>
        </div>
      </div>

      {showOpacity && onOpacityChange && (
        <div className="flex flex-col gap-2">
          <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
            불투명도
          </p>
          <div className="flex items-center justify-between gap-2">
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
        className={cn(
          "block size-[26.667px] rounded-[5.333px]",
          !active && "rounded-[6px]",
        )}
        style={{ backgroundColor: color, width: active ? 26.667 : 30, height: active ? 26.667 : 30 }}
      />
    </button>
  );
}
