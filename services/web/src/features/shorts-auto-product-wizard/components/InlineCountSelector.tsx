// ============================================================================
// Inline-wizard variant of CountSelector — replaces 5/10/15/20 with 1–10 and
// surfaces a smart-count suggestion line per Figma #12. Backend bound is
// 1..50 but the inline UI only exposes 1–10 (the typical livecommerce VOD
// length × shorts length combination rarely justifies more, and the operator
// can still drop to the legacy /export/shorts/auto/wizard route for the full
// range).
// ============================================================================

// figma: 1713-288216  (cache: .figma-cache/1713-288216_phase2_wizard-criteria.api.json)
// node-name: 쇼츠 개수 section  · spec: label=16/600 grayscale-800

"use client";

import { formatVideoTimestampHMS } from "@/lib/timeline";
import { cn } from "@/lib/utils";

const PRESETS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

/**
 * Smart-count interval: 1 suggested short per 10 minutes of video.
 * Length-independent on purpose — the prior length-aware formula
 * saturated at 10 for any video > ~10 min regardless of shorts
 * length, so the answer never differentiated a 15-min video from
 * a 60-min one. A pure time-based ratio gives a much more
 * meaningful range-to-count mapping for typical livecommerce
 * VODs (~30–90 min).
 */
const SUGGESTION_INTERVAL_MS = 10 * 60 * 1_000;

interface Props {
  value: number;
  onChange: (next: number) => void;
  /**
   * Effective range in ms used for the smart-count hint. Caller should pass
   * (endMs − startMs) when the user has constrained the range, or full
   * durationMs otherwise. Pass 0 to suppress the suggestion line.
   */
  rangeMs: number;
  /** Shorts length in seconds. Shown in the suggestion copy for context. */
  lengthSeconds: number;
  disabled?: boolean;
}

interface Suggestion {
  rangeLabel: string;
  lo: number;
  hi: number;
}

/**
 * Computes the count-suggestion band for a given range. Pure — no
 * React/DOM. Returns null when no meaningful suggestion can be made
 * (rangeMs ≤ 0).
 *
 * Formula:
 *   n = ceil(rangeMs / SUGGESTION_INTERVAL_MS), clamped to [1, 10]
 *   band = [max(1, n − 1), min(10, n + 1)]
 *
 * Length-independent — see ``SUGGESTION_INTERVAL_MS`` rationale.
 */
export function computeSmartCountSuggestion(
  rangeMs: number,
): Suggestion | null {
  if (rangeMs <= 0) return null;
  const raw = Math.ceil(rangeMs / SUGGESTION_INTERVAL_MS);
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
  const suggestion = computeSmartCountSuggestion(rangeMs);

  return (
    <div className="space-y-[12px] font-pretendard">
      <label className="block text-[16px] font-semibold text-grayscale-800">
        쇼츠 개수
      </label>
      <div className="grid grid-cols-10 gap-2">
        {PRESETS.map((preset) => {
          const isActive = value === preset;
          return (
            <button
              key={preset}
              type="button"
              onClick={() => onChange(preset)}
              disabled={disabled}
              className={cn(
                "w-full rounded-card bg-white px-1 py-3 text-base font-semibold tracking-tight transition",
                isActive
                  ? "border-2 border-heimdex-navy-500 text-heimdex-navy-500"
                  : "border border-grayscale-100 text-grayscale-500 hover:border-heimdex-navy-400 hover:text-heimdex-navy-400",
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
          className="rounded-[8px] bg-neutral-h-50 px-[12px] py-[8px] text-[12px] font-medium tracking-[-0.3px] text-grayscale-500"
          data-testid="inline-count-suggestion"
        >
          {suggestion.rangeLabel} 영상에서 {lengthSeconds}초 쇼츠라면{" "}
          <span className="font-semibold text-grayscale-800">
            {suggestion.lo}~{suggestion.hi}개
          </span>
          가 적합합니다.
        </p>
      ) : null}
    </div>
  );
}
