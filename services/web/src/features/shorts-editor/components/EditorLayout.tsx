"use client";

import type { ReactNode } from "react";

interface EditorLayoutProps {
  leftPanel: ReactNode;
  preview: ReactNode;
  rightPanel: ReactNode;
  timeline: ReactNode;
}

export function EditorLayout({ leftPanel, preview, rightPanel, timeline }: EditorLayoutProps) {
  return (
    <div className="grid h-[calc(100vh-64px)] grid-cols-[360px_1fr_420px] grid-rows-[1fr_260px] gap-0 overflow-hidden">
      {/* Left panel — overlay authoring (V2) or clip properties.
          Widened from 300px → 360px so V2 transform/effects sections fit
          without horizontal overflow (3-column X/Y/rotation row, stroke
          stepper + color swatch row). */}
      <div className="overflow-y-auto overflow-x-hidden border-r border-grayscale-100 bg-white">
        {leftPanel}
      </div>

      {/* Preview panel — center canvas surface */}
      <div className="flex items-center justify-center overflow-auto bg-grayscale-10">
        {preview}
      </div>

      {/* Right panel — 텍스트/배경/템플릿 3탭 (figma 1607:65302) */}
      <div className="overflow-y-auto border-l border-grayscale-100 bg-white">
        {rightPanel}
      </div>

      {/* Timeline panel — bottom, full width */}
      <div className="col-span-3 overflow-hidden border-t border-grayscale-100 bg-grayscale-10">
        {timeline}
      </div>
    </div>
  );
}
