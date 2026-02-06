"use client";

import { cn } from "@/lib/utils";

interface AlphaSliderProps {
  value: number;
  onChange: (value: number) => void;
}

const PRESETS = [
  { value: 0, label: "Exact", description: "Keyword matching only" },
  { value: 0.5, label: "Balanced", description: "Mix of keyword and semantic" },
  { value: 1, label: "Meaning", description: "Semantic search only" },
];

export function AlphaSlider({ value, onChange }: AlphaSliderProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-gray-700">
          Search Mode
        </label>
        <span className="text-xs text-gray-500">
          Alpha: {value.toFixed(2)}
        </span>
      </div>

      <div className="flex gap-2">
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            onClick={() => onChange(preset.value)}
            className={cn(
              "flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-all",
              value === preset.value
                ? "bg-primary-600 text-white shadow-sm"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            )}
            title={preset.description}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <input
        type="range"
        min="0"
        max="1"
        step="0.1"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-primary-600"
      />

      <div className="flex justify-between text-xs text-gray-500">
        <span>Keyword (BM25)</span>
        <span>Semantic (Vector)</span>
      </div>
    </div>
  );
}
