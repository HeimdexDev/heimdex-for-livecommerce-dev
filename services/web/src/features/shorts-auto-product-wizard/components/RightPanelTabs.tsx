// ============================================================================
// Tab strip for the auto-shorts edit-clips right panel.
//
// Two tabs in v1 — 자막 (cue text + search) and 스타일 (global subtitle style).
// 템플릿 is intentionally absent (Phase F2 follow-up).
//
// Pure presentational — caller owns the active tab state. Keyboard nav (←/→)
// rotates the active tab so screen-reader users aren't trapped clicking.
// ============================================================================

"use client";

import { useCallback, type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

export type RightPanelTab = "subtitles" | "style";

const TABS: ReadonlyArray<{ id: RightPanelTab; label: string }> = [
  { id: "subtitles", label: "자막" },
  { id: "style", label: "스타일" },
];

interface Props {
  activeTab: RightPanelTab;
  onTabChange: (tab: RightPanelTab) => void;
  className?: string;
}

export function RightPanelTabs({ activeTab, onTabChange, className }: Props) {
  const handleKey = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const idx = TABS.findIndex((t) => t.id === activeTab);
      if (idx === -1) return;
      const delta = e.key === "ArrowRight" ? 1 : -1;
      const nextIdx = (idx + delta + TABS.length) % TABS.length;
      onTabChange(TABS[nextIdx].id);
    },
    [activeTab, onTabChange],
  );

  return (
    <div
      role="tablist"
      aria-label="편집기 패널"
      className={cn("flex items-center gap-6 border-b border-gray-200", className)}
      data-testid="right-panel-tabs"
      onKeyDown={handleKey}
    >
      {TABS.map((tab) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            type="button"
            role="tab"
            key={tab.id}
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onTabChange(tab.id)}
            className={cn(
              "relative -mb-px border-b-2 px-1 py-3 text-sm font-medium transition-colors",
              isActive
                ? "border-indigo-500 text-gray-900"
                : "border-transparent text-gray-500 hover:text-gray-700",
            )}
            data-testid={`right-panel-tab-${tab.id}`}
            data-active={isActive}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
