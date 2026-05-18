"use client";

import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

// figma: 1602:41332 — color palette popover.
//
// Sections (top to bottom):
//   - Header (색상 + close)
//   - 사용 중인 색상 (figma 1602:41339) — rainbow wheel opens an in-popover
//     custom picker (hex + RGB hex shortcuts), plus a chip showing the
//     currently selected color.
//   - 기본 색상 (transparent + neutrals + 6×5 tonal grid)
//   - 선택 색상 (hex readout)
//   - 불투명도 slider (optional)

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

// figma 1602:41339 — conic-gradient rainbow swatch used as the custom-
// picker entry. Exact stops don't matter; it just signals "any color".
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
  // Custom-picker draft. Opened by clicking the rainbow wheel. Stays
  // open until the user presses 확인 (commits) or 취소 (discards).
  // Earlier impl bounced through a hidden <input type="color"> whose
  // native popup lived outside the portal — outside-click handlers
  // closed the parent palette on the very first click. The custom
  // mode is entirely DOM-local so the palette stays put.
  const [customOpen, setCustomOpen] = useState(false);
  const [draftHex, setDraftHex] = useState(
    /^#([0-9A-F]{6})$/i.test(color) ? color : "#000000",
  );

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

  const openCustom = () => {
    setDraftHex(
      /^#([0-9A-F]{6})$/i.test(color) ? color.toUpperCase() : "#000000",
    );
    setCustomOpen(true);
  };

  const confirmCustom = () => {
    const next = normaliseHex(draftHex);
    if (next) onChange(next);
    setCustomOpen(false);
  };

  return (
    <div
      // figma 1602:41332 — 260×p-[20px] white card, gap-[16px] between sections.
      className="flex w-[260px] flex-col gap-[16px] rounded-[20px] bg-white p-[20px] shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
    >
      <div className="flex items-center justify-between">
        <p className="text-[14px] font-semibold tracking-[-0.35px] text-grayscale-800">
          {customOpen ? "사용자 정의 색상" : "색상"}
        </p>
        <button
          type="button"
          onClick={customOpen ? () => setCustomOpen(false) : onClose}
          aria-label={customOpen ? "사용자 정의 닫기" : "팔레트 닫기"}
          className="text-grayscale-500 hover:text-grayscale-800"
        >
          <X className="h-5 w-5" strokeWidth={2} />
        </button>
      </div>

      {customOpen ? (
        <CustomColorPicker
          draftHex={draftHex}
          onDraftChange={setDraftHex}
          onCancel={() => setCustomOpen(false)}
          onConfirm={confirmCustom}
        />
      ) : (
        <>
          {/* figma 1602:41339 — 사용 중인 색상. Rainbow wheel opens the
              in-popover custom picker; the chip next to it shows the
              currently active color. */}
          <div className="flex flex-col gap-[8px]">
            <p className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
              사용 중인 색상
            </p>
            <div className="flex items-center gap-[10px]">
              <button
                type="button"
                onClick={openCustom}
                aria-label="사용자 정의 색상 선택"
                className="relative grid h-[30px] w-[30px] place-items-center overflow-hidden rounded-[6px] border border-grayscale-300"
                style={{ background: RAINBOW_WHEEL_GRADIENT }}
              >
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
              <div
                className={cn(
                  "relative box-border h-[30px] w-[30px] overflow-hidden rounded-[6px] border border-grayscale-300",
                )}
                style={{ backgroundColor: isTransparent ? "#FFFFFF" : color }}
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
            {/* figma 1602:41348 — diagonal line swatch acts as the "no
                color / transparent" pick. */}
            <button
              type="button"
              onClick={() => onChange("transparent")}
              aria-label="색상 없음"
              className="relative box-border h-[30px] w-[30px] overflow-hidden rounded-[6px] border border-grayscale-300 bg-white"
            >
              <span
                aria-hidden
                className="absolute left-1/2 top-1/2 block h-[2px] w-[41px] -translate-x-1/2 -translate-y-1/2 rotate-[-47deg] bg-red-h-400"
              />
            </button>
            {/* Basic + tonal grid share the same column gap so the rows
                line up. CSS grid keeps the columns rigid regardless of
                active-state border width (box-border on each chip
                ensures the cell footprint is stable too). */}
            <div className="grid grid-cols-6 gap-[8px]">
              {BASIC_COLORS.map((c) => (
                <ColorChip
                  key={c}
                  color={c}
                  active={c.toLowerCase() === color.toLowerCase()}
                  onClick={() => onChange(c)}
                />
              ))}
            </div>
            <div className="grid grid-cols-6 gap-[8px]">
              {PALETTE_COLUMNS.map((column, idx) => (
                <div key={idx} className="flex flex-col gap-[8px]">
                  {column.map((c) => (
                    <ColorChip
                      key={c}
                      color={c}
                      active={c.toLowerCase() === color.toLowerCase()}
                      onClick={() => onChange(c)}
                    />
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
                <span
                  className="block h-5 w-5 rounded-[4px]"
                  style={{ backgroundColor: color }}
                />
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
        </>
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
  // Fixed 30×30 footprint via box-border so the active ring border doesn't
  // push the cell wider and shift the columns next to it.
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`색상 ${color}`}
      className={cn(
        "box-border grid h-[30px] w-[30px] place-items-center rounded-[6px] border transition-shadow",
        active
          ? "border-[1.5px] border-heimdex-navy-300 p-[2px]"
          : "border-grayscale-300",
      )}
    >
      <span
        className="block h-full w-full rounded-[5px]"
        style={{ backgroundColor: color }}
      />
    </button>
  );
}

function CustomColorPicker({
  draftHex,
  onDraftChange,
  onCancel,
  onConfirm,
}: {
  draftHex: string;
  onDraftChange: (next: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const isValid = /^#([0-9A-F]{6})$/i.test(draftHex);
  return (
    <div className="flex flex-col gap-[12px]">
      {/* Live preview + native picker — clicking the swatch fires the
          browser's color picker via the underlying <input>, which is now
          a CHILD of the popover so outside-click handlers ignore it. */}
      <label className="flex items-center justify-between gap-[12px]">
        <span className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          색상 선택
        </span>
        <span
          className="relative box-border h-[40px] w-[100px] cursor-pointer overflow-hidden rounded-[8px] border border-grayscale-300"
          style={{ backgroundColor: isValid ? draftHex : "#000000" }}
        >
          <input
            type="color"
            value={isValid ? draftHex : "#000000"}
            onChange={(e) => onDraftChange(e.target.value.toUpperCase())}
            aria-label="색상 선택"
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          />
        </span>
      </label>

      <label className="flex flex-col gap-[6px]">
        <span className="text-[12px] font-medium tracking-[-0.3px] text-grayscale-800">
          HEX
        </span>
        <input
          type="text"
          value={draftHex}
          onChange={(e) => onDraftChange(e.target.value.toUpperCase())}
          placeholder="#RRGGBB"
          className={cn(
            "h-9 rounded-[8px] border bg-white px-2 text-[14px] tracking-[-0.35px] text-grayscale-800 focus:outline-none",
            isValid ? "border-grayscale-300" : "border-red-h-400",
          )}
        />
      </label>

      <div className="flex gap-[8px]">
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 rounded-[8px] border border-grayscale-300 px-3 py-2 text-[14px] font-semibold text-grayscale-800 hover:bg-grayscale-50"
        >
          취소
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={!isValid}
          className="flex-1 rounded-[8px] bg-heimdex-navy-500 px-3 py-2 text-[14px] font-semibold text-white hover:bg-heimdex-navy-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          확인
        </button>
      </div>
    </div>
  );
}

function normaliseHex(input: string): string | null {
  const trimmed = input.trim().toUpperCase();
  if (/^#([0-9A-F]{6})$/.test(trimmed)) return trimmed;
  if (/^#([0-9A-F]{3})$/.test(trimmed)) {
    // Expand shorthand #RGB to #RRGGBB so renderers don't have to.
    return `#${trimmed
      .slice(1)
      .split("")
      .map((c) => c + c)
      .join("")}`;
  }
  return null;
}
