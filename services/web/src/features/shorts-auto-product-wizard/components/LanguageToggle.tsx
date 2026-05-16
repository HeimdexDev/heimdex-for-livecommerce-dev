// ============================================================================
// 언어 — 한국어 / 영어
//
// Phase 4 ships ``ko`` end-to-end. ``en`` is the Phase 7 deliverable
// (alignment tokenizer split for English narration + EN-only LLM picker
// prompt). Until then selecting ``en`` is accepted at the API level
// (backend stores it on the parent row) but downstream alignment defaults
// to the Korean tokenizer rules — minor false-negative rate on narration
// matching, no hard failure.
// ============================================================================

"use client";

import type { Language } from "@/lib/types/shorts-auto-product-wizard";

interface Props {
  value: Language;
  onChange: (next: Language) => void;
}

const OPTIONS: Array<{ value: Language; label: string }> = [
  { value: "ko", label: "한국어" },
  { value: "en", label: "영어" },
];

export function LanguageToggle({ value, onChange }: Props) {
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-700">언어</label>
      <div className="flex gap-2">
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`rounded-md border px-3 py-1.5 text-sm transition ${
              value === opt.value
                ? "border-indigo-500 bg-indigo-500 text-white"
                : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
            }`}
            data-testid={`language-${opt.value}`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
