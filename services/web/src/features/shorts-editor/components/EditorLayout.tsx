"use client";

import type { ReactNode } from "react";

interface EditorLayoutProps {
  leftPanel: ReactNode;
  preview: ReactNode;
  rightPanel: ReactNode;
  timeline: ReactNode;
}

// figma: 1602:37722 / 1602:37844 / 1663:45752 — editor body = three cards
// in the upper row (subtitle 434×586, video 352×626, text/bg/template 331×586
// — left/right wrappers add 20px padding on every side) plus the timeline
// anchored at the bottom. All wrappers share the dialog radius and card
// shadow, separated by 20px gaps. Top row uses the figma 626px outer height
// so the visible content matches the figma frame exactly.
export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="flex h-full flex-col gap-[20px] overflow-hidden bg-grayscale-10">
      <div className="flex h-[626px] shrink-0 items-stretch gap-[20px]">
        <div className="flex h-full w-[474px] min-w-0 flex-col overflow-hidden rounded-dialog bg-white shadow-card">
          {leftPanel}
        </div>
        <div className="flex h-full w-[352px] shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-black shadow-card">
          {preview}
        </div>
        <div className="flex h-full w-[371px] flex-col overflow-hidden rounded-dialog bg-white shadow-card">
          {rightPanel}
        </div>
      </div>
      <div className="h-[260px] overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
    </div>
  );
}
