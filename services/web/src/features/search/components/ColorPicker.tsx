"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface ColorPickerProps {
  value: string | undefined;
  onChange: (hex: string | undefined) => void;
}

const COLOR_SWATCHES = [
  // Warm
  { hex: "#ef4444", label: "빨강" },
  { hex: "#f97316", label: "주황" },
  { hex: "#eab308", label: "노랑" },
  { hex: "#f472b6", label: "분홍" },
  { hex: "#a855f7", label: "보라" },
  // Cool
  { hex: "#3b82f6", label: "파랑" },
  { hex: "#06b6d4", label: "하늘" },
  { hex: "#22c55e", label: "초록" },
  { hex: "#14b8a6", label: "청록" },
  { hex: "#6366f1", label: "남색" },
  // Neutral
  { hex: "#f5f5f4", label: "흰색" },
  { hex: "#d1d5db", label: "밝은 회색" },
  { hex: "#6b7280", label: "회색" },
  { hex: "#92400e", label: "갈색" },
  { hex: "#171717", label: "검정" },
];

export default function ColorPicker({ value, onChange }: ColorPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen]);

  return (
    <div className="relative" ref={panelRef}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => {
          if (value) {
            onChange(undefined);
          } else {
            setIsOpen((o) => !o);
          }
        }}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
          value
            ? "bg-white text-gray-900 shadow-sm ring-1 ring-gray-200"
            : isOpen
              ? "bg-white text-gray-900 shadow-sm"
              : "text-gray-500 hover:text-gray-700",
        )}
      >
        {value ? (
          <>
            <span
              className="inline-block h-3 w-3 rounded-full ring-1 ring-inset ring-black/10"
              style={{ backgroundColor: value }}
            />
            색상
            <span className="text-gray-400 hover:text-gray-600">✕</span>
          </>
        ) : (
          <>
            <span className="text-sm leading-none" aria-hidden>🎨</span>
            색상
          </>
        )}
      </button>

      {/* Dropdown */}
      {isOpen && !value && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-[220px] rounded-xl border border-gray-200 bg-white p-3 shadow-xl">
          <p className="mb-2 text-[11px] font-medium text-gray-400">색상 선택</p>

          {/* Swatch grid */}
          <div className="grid grid-cols-5 gap-2">
            {COLOR_SWATCHES.map(({ hex, label }) => (
              <button
                key={hex}
                type="button"
                title={label}
                onClick={() => {
                  onChange(hex);
                  setIsOpen(false);
                }}
                className="group relative h-8 w-8 rounded-lg transition-transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-primary-400 focus:ring-offset-1"
                style={{ backgroundColor: hex }}
              >
                <span
                  className="absolute inset-0 rounded-lg ring-1 ring-inset ring-black/10"
                />
              </button>
            ))}
          </div>

          {/* Divider + custom color */}
          <div className="mt-3 flex items-center gap-2 border-t border-gray-100 pt-3">
            <input
              id="color-custom-input"
              type="color"
              defaultValue="#6366f1"
              className="h-8 w-8 shrink-0 cursor-pointer appearance-none rounded-lg border-0 bg-transparent p-0 [&::-webkit-color-swatch-wrapper]:p-0 [&::-webkit-color-swatch]:rounded-lg [&::-webkit-color-swatch]:border-0"
            />
            <button
              type="button"
              onClick={() => {
                const input = document.getElementById("color-custom-input") as HTMLInputElement | null;
                if (input) {
                  onChange(input.value);
                  setIsOpen(false);
                }
              }}
              className="rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-200"
            >
              적용
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
