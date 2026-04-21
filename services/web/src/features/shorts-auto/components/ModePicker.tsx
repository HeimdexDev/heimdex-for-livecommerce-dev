"use client";

import { cn } from "@/lib/utils";
import { MODE_OPTIONS } from "../lib/types";
import type { ScoringModeRequest } from "@/lib/types";

interface ModePickerProps {
  value: ScoringModeRequest;
  onChange: (mode: ScoringModeRequest) => void;
  disabled?: boolean;
}

export function ModePicker({ value, onChange, disabled = false }: ModePickerProps) {
  return (
    <div
      role="radiogroup"
      aria-label="자동 쇼츠 생성 모드"
      className="grid gap-3 sm:grid-cols-3"
    >
      {MODE_OPTIONS.map((opt) => {
        const selected = opt.value === value;
        return (
          <label
            key={opt.value}
            className={cn(
              "flex cursor-pointer flex-col gap-1 rounded-xl border p-4 transition-colors",
              "focus-within:ring-2 focus-within:ring-indigo-500",
              selected
                ? "border-indigo-400 bg-indigo-50/60"
                : "border-gray-200 bg-white hover:border-gray-300",
              disabled && "cursor-not-allowed opacity-60",
            )}
          >
            <input
              type="radio"
              name="auto-shorts-mode"
              value={opt.value}
              checked={selected}
              disabled={disabled}
              onChange={() => onChange(opt.value)}
              className="sr-only"
              aria-describedby={`auto-shorts-mode-${opt.value}-desc`}
            />
            <div className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn(
                  "inline-flex h-4 w-4 items-center justify-center rounded-full border",
                  selected ? "border-indigo-500" : "border-gray-300",
                )}
              >
                {selected && <span className="h-2 w-2 rounded-full bg-indigo-500" />}
              </span>
              <span className="text-sm font-medium text-gray-900">{opt.label}</span>
            </div>
            <p id={`auto-shorts-mode-${opt.value}-desc`} className="text-xs text-gray-500">
              {opt.description}
            </p>
          </label>
        );
      })}
    </div>
  );
}
