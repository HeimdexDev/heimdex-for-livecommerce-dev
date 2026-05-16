// ============================================================================
// 쇼츠 길이 선택 (15/30/60/90/120 + 직접입력)
//
// Bound range: 10..120 seconds (matches backend ScanOrderCreateRequest's
// ``length_seconds: int = Field(..., ge=10, le=120)``). The custom input
// clamps locally so the user sees the rejection before submit.
// ============================================================================

"use client";

import { useState } from "react";

const PRESETS = [15, 30, 60, 90, 120] as const;
const MIN = 10;
const MAX = 120;

interface Props {
  value: number;
  onChange: (next: number) => void;
}

export function LengthSelector({ value, onChange }: Props) {
  const [customDraft, setCustomDraft] = useState<string>("");
  const isPresetActive = (PRESETS as readonly number[]).includes(value);

  const handlePresetClick = (preset: number) => {
    onChange(preset);
    setCustomDraft("");
  };

  const handleCustomChange = (raw: string) => {
    setCustomDraft(raw);
    const parsed = Number.parseInt(raw, 10);
    if (Number.isNaN(parsed)) return;
    const clamped = Math.max(MIN, Math.min(MAX, parsed));
    onChange(clamped);
  };

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-700">
        쇼츠 길이
      </label>
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            onClick={() => handlePresetClick(preset)}
            className={`rounded-md border px-3 py-1.5 text-sm transition ${
              isPresetActive && value === preset
                ? "border-indigo-500 bg-indigo-500 text-white"
                : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
            }`}
            data-testid={`length-preset-${preset}`}
          >
            {preset}초
          </button>
        ))}
        <input
          type="number"
          min={MIN}
          max={MAX}
          placeholder="직접입력"
          value={customDraft || (isPresetActive ? "" : String(value))}
          onChange={(e) => handleCustomChange(e.target.value)}
          className="w-24 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          data-testid="length-custom-input"
        />
      </div>
      <p className="text-xs text-gray-500">
        {MIN}초 이상 {MAX}초 이하 (현재 {value}초)
      </p>
    </div>
  );
}
