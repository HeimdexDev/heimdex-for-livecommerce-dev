// ============================================================================
// Inline-wizard variant of LengthSelector — drops the "직접입력" custom input
// and helper text per Figma #12. Same underlying bounds as the legacy version
// (matches backend ``length_seconds: ge=10, le=120``).
// ============================================================================

// figma: 1713-288216  (cache: .figma-cache/1713-288216_phase2_wizard-criteria.api.json)
// node-name: 쇼츠 길이 section  · spec: label=16/600 grayscale-800

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
    <div className="space-y-[12px] font-pretendard">
      <label className="block text-[16px] font-semibold text-grayscale-800">
        쇼츠 길이
      </label>
      <div className="flex flex-wrap gap-[12px]">
        {PRESETS.map((preset) => {
          const isActive = value === preset;
          return (
            <button
              key={preset}
              type="button"
              onClick={() => onChange(preset)}
              disabled={disabled}
              className={cn(
                "min-w-[88px] rounded-[10px] bg-white px-[16px] py-[12px] text-[16px] font-semibold tracking-[-0.4px] transition",
                isActive
                  ? "border-2 border-heimdex-navy-500 text-heimdex-navy-500"
                  : "border border-grayscale-100 text-grayscale-500 hover:border-heimdex-navy-400 hover:text-heimdex-navy-400",
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
