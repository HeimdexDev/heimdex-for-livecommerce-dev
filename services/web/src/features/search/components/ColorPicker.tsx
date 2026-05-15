"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface ColorPickerProps {
  /** Selected color family ID (e.g. "pink"), or undefined for no selection */
  value: string | undefined;
  /** Called with family ID to select, or undefined to clear */
  onChange: (family: string | undefined) => void;
}

/**
 * Broad color families for dominant-color search.
 * Each chip represents a family, not an exact shade.
 * The representative hex is for display only — the backend
 * receives the family ID and builds a broad query vector.
 */
const COLOR_FAMILIES = [
  // Warm
  { id: "red", hex: "#ef4444", label: "빨강" },
  { id: "orange", hex: "#f97316", label: "주황" },
  { id: "yellow", hex: "#eab308", label: "노랑" },
  { id: "pink", hex: "#f472b6", label: "분홍" },
  { id: "purple", hex: "#a855f7", label: "보라" },
  // Cool
  { id: "blue", hex: "#3b82f6", label: "파랑" },
  { id: "teal", hex: "#14b8a6", label: "청록" },
  { id: "green", hex: "#22c55e", label: "초록" },
  // Neutral
  { id: "brown", hex: "#92400e", label: "갈색" },
  { id: "white", hex: "#f5f5f4", label: "흰색" },
  { id: "gray", hex: "#9ca3af", label: "회색" },
  { id: "black", hex: "#171717", label: "검정" },
];

/** Look up the display hex for a family ID (for the trigger chip). */
function familyHex(familyId: string): string {
  return COLOR_FAMILIES.find((f) => f.id === familyId)?.hex ?? "#6b7280";
}

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
              style={{ backgroundColor: familyHex(value) }}
            />
            {COLOR_FAMILIES.find((f) => f.id === value)?.label ?? "색상"}
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
          <p className="mb-2 text-[11px] font-medium text-gray-400">색상 계열 선택</p>

          {/* Family chip grid */}
          <div className="grid grid-cols-4 gap-2">
            {COLOR_FAMILIES.map(({ id, hex, label }) => (
              <button
                key={id}
                type="button"
                title={label}
                onClick={() => {
                  onChange(id);
                  setIsOpen(false);
                }}
                className="group flex flex-col items-center gap-1 rounded-lg p-1.5 transition-colors hover:bg-gray-50"
              >
                <span
                  className="h-7 w-7 rounded-lg ring-1 ring-inset ring-black/10 transition-transform group-hover:scale-110"
                  style={{ backgroundColor: hex }}
                />
                <span className="text-[10px] leading-none text-gray-500 group-hover:text-gray-700">
                  {label}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
