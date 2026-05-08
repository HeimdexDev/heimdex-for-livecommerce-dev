// ============================================================================
// Inline-wizard variant of CountSelector — replaces 5/10/15/20 with 1–10 and
// surfaces a smart-count suggestion line per Figma #12. Backend bound is
// 1..50 but the inline UI only exposes 1–10 (the typical livecommerce VOD
// length × shorts length combination rarely justifies more, and the operator
// can still drop to the legacy /export/shorts/auto/wizard route for the full
// range).
// ============================================================================

"use client";

import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

const PRESETS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

interface Props {
  value: number;
  onChange: (next: number) => void;
  /**
   * Effective range in ms used for the smart-count hint. Caller should pass
   * (endMs − startMs) when the user has constrained the range, or full
   * durationMs otherwise. Pass 0 to suppress the suggestion line.
   */
  rangeMs: number;
  /** Shorts length in seconds. Drives the suggestion compute. */
  lengthSeconds: number;
  disabled?: boolean;
}

interface Suggestion {
  rangeLabel: string;
  lo: number;
  hi: number;
}

/**
 * Computes the count-suggestion band for a given range and shorts length.
 * Pure — no React/DOM. Returns null when no meaningful suggestion can be
 * made (rangeMs ≤ 0 or lengthSeconds ≤ 0).
 *
 * Formula (per locked decision #4):
 *   n = ceil(rangeMs / (lengthSeconds × 1000)), clamped to [1, 10]
 *   band = [max(1, n − 1), min(10, n + 1)]
 */
export function computeSmartCountSuggestion(
  rangeMs: number,
  lengthSeconds: number,
): Suggestion | null {
  if (rangeMs <= 0 || lengthSeconds <= 0) return null;
  const lengthMs = lengthSeconds * 1000;
  const raw = Math.ceil(rangeMs / lengthMs);
  const clamped = Math.max(1, Math.min(10, raw));
  return {
    rangeLabel: formatVideoTimestampHMS(rangeMs),
    lo: Math.max(1, clamped - 1),
    hi: Math.min(10, clamped + 1),
  };
}

export function InlineCountSelector({
  value,
  onChange,
  rangeMs,
  lengthSeconds,
  disabled,
}: Props) {
  const suggestion = computeSmartCountSuggestion(rangeMs, lengthSeconds);

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-gray-900">
        쇼츠 개수
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
                "min-w-[48px] rounded-md border px-3 py-2 text-sm font-medium transition",
                isActive
                  ? "border-gray-900 bg-white text-gray-900 ring-2 ring-gray-900"
                  : "border-gray-200 bg-white text-gray-500 hover:border-gray-400 hover:text-gray-700",
                disabled && "cursor-not-allowed opacity-50",
              )}
              data-testid={`inline-count-preset-${preset}`}
              data-active={isActive}
            >
              {preset}개
            </button>
          );
        })}
      </div>
      {suggestion ? (
        <p
          className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-600"
          data-testid="inline-count-suggestion"
        >
          {suggestion.rangeLabel} 영상에서 {lengthSeconds}초 쇼츠라면{" "}
          <span className="font-semibold text-gray-900">
            {suggestion.lo}~{suggestion.hi}개
          </span>
          가 적합합니다.
        </p>
      ) : null}
    </div>
  );
}
