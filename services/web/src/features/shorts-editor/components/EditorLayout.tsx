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
    <div className="grid h-[calc(100vh-64px)] grid-cols-[300px_1fr_420px] grid-rows-[1fr_260px] gap-0 overflow-hidden">
      {/* Left panel — text overlay authoring or clip properties */}
      <div className="overflow-y-auto border-r border-gray-200 bg-white">
        {leftPanel}
      </div>

      {/* Preview panel — center canvas surface */}
      <div className="flex items-center justify-center overflow-hidden bg-neutral-100">
        {preview}
      </div>

      {/* Right panel — scene list */}
      <div className="overflow-y-auto border-l border-gray-200 bg-white">
        {rightPanel}
      </div>

      {/* Timeline panel — bottom, full width */}
      <div className="col-span-3 overflow-hidden border-t border-gray-200 bg-gray-50">
        {timeline}
      </div>
    </div>
  );
}
