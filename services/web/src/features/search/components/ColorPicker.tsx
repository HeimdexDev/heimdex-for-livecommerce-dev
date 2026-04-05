"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface ColorPickerProps {
  value: string | undefined;
  onChange: (hex: string | undefined) => void;
}

const COLOR_SWATCHES = [
  // Row 1: warm tones
  { hex: "#ef4444", label: "Red" },
  { hex: "#f97316", label: "Orange" },
  { hex: "#eab308", label: "Yellow" },
  { hex: "#f472b6", label: "Pink" },
  { hex: "#a855f7", label: "Purple" },
  // Row 2: cool tones
  { hex: "#3b82f6", label: "Blue" },
  { hex: "#06b6d4", label: "Cyan" },
  { hex: "#22c55e", label: "Green" },
  { hex: "#14b8a6", label: "Teal" },
  { hex: "#6366f1", label: "Indigo" },
  // Row 3: neutrals + earth
  { hex: "#ffffff", label: "White" },
  { hex: "#d1d5db", label: "Light gray" },
  { hex: "#6b7280", label: "Gray" },
  { hex: "#92400e", label: "Brown" },
  { hex: "#000000", label: "Black" },
];

export default function ColorPicker({ value, onChange }: ColorPickerProps) {
  const [showCustom, setShowCustom] = useState(false);

  return (
    <div className="relative">
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => {
          if (value) {
            onChange(undefined);
          } else {
            setShowCustom((s) => !s);
          }
        }}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all",
          value
            ? "bg-white text-gray-900 shadow-sm ring-1 ring-gray-200"
            : showCustom
              ? "bg-white text-gray-900 shadow-sm"
              : "text-gray-500 hover:text-gray-700",
        )}
      >
        {value ? (
          <>
            <span
              className="h-3 w-3 rounded-full border border-gray-300"
              style={{ backgroundColor: value }}
            />
            색상
            <span className="ml-0.5 text-gray-400 hover:text-gray-600">✕</span>
          </>
        ) : (
          <>
            <span className="text-sm leading-none" aria-hidden>🎨</span>
            색상
          </>
        )}
      </button>

      {/* Dropdown panel */}
      {showCustom && !value && (
        <div className="absolute top-full left-0 z-50 mt-2 rounded-lg border border-gray-200 bg-white p-3 shadow-lg">
          {/* Swatch grid */}
          <div className="grid grid-cols-5 gap-1.5">
            {COLOR_SWATCHES.map(({ hex, label }) => (
              <button
                key={hex}
                type="button"
                title={label}
                onClick={() => {
                  onChange(hex);
                  setShowCustom(false);
                }}
                className={cn(
                  "h-7 w-7 rounded-md border transition-transform hover:scale-110",
                  hex === "#ffffff"
                    ? "border-gray-300"
                    : "border-transparent",
                )}
                style={{ backgroundColor: hex }}
              />
            ))}
          </div>

          {/* Custom color input */}
          <div className="mt-2.5 flex items-center gap-2 border-t border-gray-100 pt-2.5">
            <input
              type="color"
              className="h-7 w-7 cursor-pointer rounded border-0 p-0"
              onChange={(e) => {
                onChange(e.target.value);
                setShowCustom(false);
              }}
            />
            <span className="text-xs text-gray-400">커스텀 색상</span>
          </div>
        </div>
      )}
    </div>
  );
}
