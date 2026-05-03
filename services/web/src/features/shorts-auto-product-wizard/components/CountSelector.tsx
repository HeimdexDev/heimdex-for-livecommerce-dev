// ============================================================================
// 생성할 쇼츠 개수 (5/10/15/20 + 직접입력)
//
// Bound range: 1..50 (matches backend's ``requested_count: int = Field(...,
// ge=1, le=50)``). Aggregate output cap (count × length ≤ 1800s) is enforced
// server-side at submit; the criteria page surfaces it as a 422 message.
// ============================================================================

"use client";

import { useState } from "react";

const PRESETS = [5, 10, 15, 20] as const;
const MIN = 1;
const MAX = 50;

interface Props {
  value: number;
  onChange: (next: number) => void;
}

export function CountSelector({ value, onChange }: Props) {
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
        생성할 쇼츠 개수
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
            data-testid={`count-preset-${preset}`}
          >
            {preset}개
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
          data-testid="count-custom-input"
        />
      </div>
      <p className="text-xs text-gray-500">
        {MIN}개 이상 {MAX}개 이하 (현재 {value}개)
      </p>
    </div>
  );
}
