"use client";

import type { ReactNode } from "react";

interface EditorLayoutProps {
  leftPanel: ReactNode;
  preview: ReactNode;
  rightPanel: ReactNode;
  timeline: ReactNode;
}

// figma: 1602:37722 / 1602:37844 / 1663:45752 — editor body = three cards
// in the upper row (subtitle, video preview, text/bg/template) plus the
// timeline anchored at the bottom. All wrappers share the dialog radius
// and card shadow and are separated by 20px gaps so each pane reads as a
// distinct surface against the grayscale-10 page background.
export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="flex h-full flex-col gap-[20px] overflow-hidden bg-grayscale-10">
      <div className="flex min-h-0 flex-1 gap-[20px]">
        <div className="flex w-[360px] flex-col overflow-y-auto overflow-x-hidden rounded-dialog bg-white shadow-card">
          {leftPanel}
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-center overflow-hidden rounded-dialog bg-white shadow-card">
          {preview}
        </div>
        <div className="flex w-[420px] flex-col overflow-hidden rounded-dialog bg-white shadow-card">
          {rightPanel}
        </div>
      </div>
      <div className="h-[260px] overflow-hidden rounded-dialog bg-white shadow-card">
        {timeline}
      </div>
    </div>
  );
}
