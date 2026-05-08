// ============================================================================
// Inline-wizard variant of LengthSelector — drops the "직접입력" custom input
// and helper text per Figma #12. Same underlying bounds as the legacy version
// (matches backend ``length_seconds: ge=10, le=120``).
// ============================================================================

"use client";

import { cn } from "@/lib/utils";

const PRESETS = [15, 30, 60, 90, 120] as const;

interface Props {
  value: number;
  onChange: (next: number) => void;
  disabled?: boolean;
}

export function InlineLengthSelector({ value, onChange, disabled }: Props) {
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-900">
        쇼츠 길이
      </label>
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((preset) => {
          const isActive = value === preset;
          return (
            <button
              key={preset}
              type="button"
              onClick={() => onChange(preset)}
              disabled={disabled}
              className={cn(
                "min-w-[64px] rounded-md border px-4 py-2 text-sm font-medium transition",
                isActive
                  ? "border-gray-900 bg-white text-gray-900 ring-2 ring-gray-900"
                  : "border-gray-200 bg-white text-gray-500 hover:border-gray-400 hover:text-gray-700",
                disabled && "cursor-not-allowed opacity-50",
              )}
              data-testid={`inline-length-preset-${preset}`}
              data-active={isActive}
            >
              {preset}초
            </button>
          );
        })}
      </div>
    </div>
  );
}
