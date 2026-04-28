"use client";

import { cn } from "@/lib/utils";
import type { ScoringModeRequest } from "@/lib/types";

import { MODE_OPTIONS } from "../lib/types";
import { PersonSelect } from "./PersonSelect";

interface ModeTabsProps {
  videoId: string;
  mode: ScoringModeRequest;
  personClusterId: string | null;
  isLoading: boolean;
  onModeChange: (next: ScoringModeRequest) => void;
  onPersonChange: (personClusterId: string | null) => void;
}

/**
 * Phase 2 mode picker — Option 2 from the plan: an in-page tab strip
 * above the candidate list. Replaces PR 3's ModeReselectModal so the
 * user can flip between modes without a modal context-switch.
 *
 * The page maintains a per-(videoId, mode, personClusterId) cache of
 * AutoSelectResponse, so clicking a tab the user has already seen is
 * instant. Cache miss fires a fresh auto-select.
 *
 * Inline person picker (Option 6 hybrid from the plan): when 인물
 * 중심 is the active tab AND no person is picked yet, the picker
 * expands directly below the tab strip with a "select a person"
 * blocking message. Generation is suppressed by the page until a
 * person is selected.
 */
export function ModeTabs({
  videoId,
  mode,
  personClusterId,
  isLoading,
  onModeChange,
  onPersonChange,
}: ModeTabsProps) {
  return (
    <div className="space-y-2">
      <div
        role="tablist"
        aria-label="자동 쇼츠 모드"
        className="inline-flex items-center rounded-lg bg-gray-100 p-0.5"
      >
        {MODE_OPTIONS.map((opt) => {
          const selected = opt.value === mode;
          return (
            <button
              key={opt.value}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`mode-tab-panel-${opt.value}`}
              disabled={isLoading}
              onClick={() => onModeChange(opt.value)}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                selected
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-800",
                isLoading && "cursor-not-allowed opacity-60",
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {mode === "human" && (
        <div
          id="mode-tab-panel-human"
          role="tabpanel"
          aria-labelledby="mode-tab-human"
          className="flex flex-col gap-1.5"
        >
          <div className="max-w-md">
            <PersonSelect
              videoId={videoId}
              value={personClusterId}
              onChange={onPersonChange}
              disabled={isLoading}
            />
          </div>
          {!personClusterId && (
            <p className="text-[11px] text-gray-500">
              인물을 선택하면 해당 인물이 등장하는 장면만 모아 자동으로 쇼츠를 만들어 드립니다.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
