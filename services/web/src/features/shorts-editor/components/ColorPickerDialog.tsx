"use client";

// figma: 1602:41332

import { useEffect } from "react";
import { cn } from "@/lib/utils";

interface ColorAlpha {
  color: string;
  alpha: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  value: ColorAlpha;
  onChange: (next: ColorAlpha) => void;
  recentColors: string[];
}

const NEUTRAL_ROW = ["#000000", "#434343", "#7b7b7b", "#c4c4c4", "#e9e9e9", "#ffffff"];

const COLOR_GRID: string[][] = [
  ["#f8cec0", "#fcefc8", "#e6efd7", "#c0e8fe", "#cdd3ef", "#dbc2e5"],
  ["#f1916e", "#f9ce5b", "#b6d18b", "#73cafc", "#a0aad6", "#b073c3"],
  ["#ec613b", "#f3a33e", "#88af53", "#47a7ed", "#5f6fbb", "#8f40ab"],
  ["#cc552f", "#ef7934", "#61873d", "#3787cb", "#3b4fa5", "#613095"],
  ["#a34426", "#bf6129", "#4e6c30", "#2b6ca2", "#2f4083", "#4e2677"],
];

const PLUS_WHEEL_GRADIENT =
  "conic-gradient(from 90deg, #f9ce5b 0%, #f3984b 5.53%, #ec613b 11.06%, #df7d4f 13.82%, #d19963 16.59%, #b6d18b 22.12%, #7fbcbc 31.06%, #63b2d5 35.53%, #47a7ed 40%, #5f6fbb 60%, #7758b3 70%, #8f40ab 80%, #aa6497 85%, #c48783 90%, #dfab6f 95%, #f9ce5b 100%)";

export function ColorPickerDialog({
  open,
  onClose,
  value,
  onChange,
  recentColors,
}: Props) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const pickColor = (color: string) => onChange({ color, alpha: value.alpha });
  const setAlpha = (alpha: number) => onChange({ color: value.color, alpha });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="색상 선택"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className={cn(
          "flex w-[260px] flex-col items-end justify-center gap-[16px] overflow-clip rounded-dialog bg-white p-[20px] shadow-dialog",
        )}
      >
        <header className="flex w-full items-center justify-between">
          <p className="font-pretendard text-[14px] font-semibold leading-[1.4] tracking-[-0.35px] text-grayscale-800">
            색상
          </p>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            className="grid h-[20px] w-[20px] place-items-center text-grayscale-800"
          >
            <CloseGlyph />
          </button>
        </header>

        <section className="flex w-full flex-col items-start gap-[8px]">
          <p className="font-pretendard text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-800">
            사용 중인 색상
          </p>
          <div className="flex items-center justify-center gap-[11px]">
            <button
              type="button"
              aria-label="색상 추가"
              className="flex h-[30px] w-[30px] items-center justify-center rounded-[6px] border border-grayscale-300"
              style={{ background: PLUS_WHEEL_GRADIENT }}
            >
              <span className="grid h-[20px] w-[20px] place-items-center rounded-full bg-white text-grayscale-800">
                <PlusGlyph size={16} />
              </span>
            </button>
            {recentColors.slice(0, 2).map((rc, i) => {
              const isSelected =
                rc.toLowerCase() === value.color.toLowerCase();
              return (
                <button
                  key={`${rc}-${i}`}
                  type="button"
                  aria-label={`최근 색상 ${rc}`}
                  onClick={() => pickColor(rc)}
                  className={cn(
                    "flex items-center rounded-[7.111px] p-[2.667px]",
                    isSelected
                      ? "border-[1.333px] border-solid border-heimdex-navy-300"
                      : "border-[1.333px] border-solid border-transparent",
                  )}
                >
                  <span
                    className="block h-[26.667px] w-[26.667px] rounded-[5.333px] border-[0.889px] border-grayscale-300"
                    style={{ backgroundColor: rc }}
                  />
                </button>
              );
            })}
          </div>
        </section>

        <section className="flex w-full flex-col items-start gap-[8px]">
          <p className="font-pretendard text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-800">
            기본 색상
          </p>
          <button
            type="button"
            aria-label="투명"
            onClick={() => pickColor("transparent")}
            className="relative h-[30px] w-[30px] overflow-hidden rounded-[6px] border border-grayscale-300 bg-white"
          >
            <svg
              viewBox="0 0 30 30"
              preserveAspectRatio="none"
              className="absolute inset-0 h-full w-full"
            >
              <line
                x1="2"
                y1="28"
                x2="28"
                y2="2"
                stroke="#d81d2f"
                strokeWidth="2"
              />
            </svg>
          </button>
          <div className="flex w-full items-center justify-between">
            {NEUTRAL_ROW.map((hex) => (
              <SwatchButton
                key={hex}
                hex={hex}
                selected={hex.toLowerCase() === value.color.toLowerCase()}
                onClick={() => pickColor(hex)}
              />
            ))}
          </div>
          <div className="flex flex-col gap-[10px]">
            {COLOR_GRID.map((row, ri) => (
              <div
                key={ri}
                className="flex items-center justify-between gap-[8px]"
              >
                {row.map((hex) => (
                  <SwatchButton
                    key={hex}
                    hex={hex}
                    selected={hex.toLowerCase() === value.color.toLowerCase()}
                    onClick={() => pickColor(hex)}
                  />
                ))}
              </div>
            ))}
          </div>
        </section>

        <section className="flex w-full flex-col items-start gap-[8px]">
          <p className="font-pretendard text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-800">
            선택 색상
          </p>
          <div className="flex w-full flex-col items-end justify-center">
            <div className="flex w-[100px] items-center gap-[10px] rounded-[6px] border-[0.909px] border-solid border-grayscale-300 p-[5px]">
              <span
                className="block h-[20px] w-[20px] rounded-[4px]"
                style={{ backgroundColor: value.color }}
              />
              <input
                type="text"
                value={value.color}
                onChange={(e) => pickColor(e.target.value)}
                aria-label="hex 입력"
                className="w-full min-w-0 bg-transparent font-pretendard text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-800 outline-none"
              />
            </div>
          </div>
        </section>

        <section className="flex w-full flex-col items-start gap-[8px]">
          <p className="font-pretendard text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-grayscale-800">
            불투명도
          </p>
          <div className="flex w-full items-center justify-between">
            <div className="flex w-[156px] items-center justify-center gap-[8px] overflow-clip rounded-[8px] px-[6px]">
              <button
                type="button"
                aria-label="불투명도 감소"
                onClick={() => setAlpha(Math.max(0, value.alpha - 1))}
                className="grid h-[20px] w-[20px] place-items-center text-grayscale-800"
              >
                <MinusGlyph size={20} />
              </button>
              <input
                type="range"
                min={0}
                max={100}
                value={value.alpha}
                onChange={(e) => setAlpha(Number(e.target.value))}
                aria-label="불투명도"
                className="h-[2px] flex-1 accent-grayscale-800"
              />
              <button
                type="button"
                aria-label="불투명도 증가"
                onClick={() => setAlpha(Math.min(100, value.alpha + 1))}
                className="grid h-[20px] w-[20px] place-items-center text-grayscale-800"
              >
                <PlusGlyph size={20} />
              </button>
            </div>
            <div className="flex items-center rounded-[10px] border border-solid border-grayscale-300 bg-white px-[8px] py-[10px]">
              <p className="font-pretendard text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-grayscale-800">
                {Math.round(value.alpha)}%
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

interface SwatchProps {
  hex: string;
  selected: boolean;
  onClick: () => void;
}

function SwatchButton({ hex, selected, onClick }: SwatchProps) {
  return (
    <button
      type="button"
      aria-label={hex}
      onClick={onClick}
      className={cn(
        "h-[30px] w-[30px] rounded-[6px] border border-solid",
        selected ? "border-heimdex-navy-500" : "border-grayscale-300",
      )}
      style={{ backgroundColor: hex }}
    />
  );
}

function CloseGlyph() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-full w-full"
    >
      <path d="M18 6L6 18M6 6l12 12" />
    </svg>
  );
}

function PlusGlyph({ size = 20 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ width: size, height: size }}
    >
      <path d="M12 5v14m-7-7h14" />
    </svg>
  );
}

function MinusGlyph({ size = 20 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ width: size, height: size }}
    >
      <path d="M5 12h14" />
    </svg>
  );
}
