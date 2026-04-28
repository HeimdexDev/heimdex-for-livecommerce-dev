"use client";

import type { ReactNode } from "react";

interface AutoShortsLayoutProps {
  /** Top breadcrumb + page header. */
  header: ReactNode;
  /** Compact mode picker summary (option 5 in PR 3 / option 2 tabs in PR 5). */
  modeBar?: ReactNode;
  /** Left rail — generated/candidate clip list. */
  candidateList: ReactNode;
  /** Center pane — proxy-stitched player. */
  player: ReactNode;
  /** Right rail — inspector panel (title, source timeline, script). */
  inspector: ReactNode;
}

/**
 * 3-column layout shell for /export/shorts/auto.
 *
 * Modeled on ``features/shorts-editor/components/EditorLayout.tsx`` but
 * with the bottom timeline row dropped — auto-shorts is a candidate
 * browser, not a timeline editor. Light theme matches the rest of the
 * app per locked decision in the plan (no dark mode in this initiative).
 *
 * Column widths: 320px / fluid / 380px. Slightly wider right rail than
 * the editor so the inspector can fit a comfortable script readout
 * without horizontal cramping.
 */
export function AutoShortsLayout({
  header,
  modeBar,
  candidateList,
  player,
  inspector,
}: AutoShortsLayoutProps) {
  return (
    <div className="font-pretendard flex h-screen flex-col overflow-hidden bg-gray-50">
      {/* Header strip — breadcrumb + page title. Stays light-weight; the
          mode-bar lives below for visual separation. */}
      <div className="border-b border-gray-200 bg-white px-6 pt-4 pb-3">
        {header}
      </div>

      {/* Compact mode-bar slot. Optional so the layout still renders
          before mode is committed (PR 3 ships option 5: a summary line
          here that opens a modal; PR 5 will swap in tabs). */}
      {modeBar && (
        <div className="border-b border-gray-200 bg-white px-6 py-2">
          {modeBar}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-[320px_1fr_380px] gap-0">
        <div className="overflow-y-auto border-r border-gray-200 bg-white">
          {candidateList}
        </div>
        <div className="flex items-center justify-center overflow-hidden bg-neutral-100">
          {player}
        </div>
        <div className="overflow-y-auto border-l border-gray-200 bg-white">
          {inspector}
        </div>
      </div>
    </div>
  );
}
