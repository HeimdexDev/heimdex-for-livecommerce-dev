"use client";

import { useCallback } from "react";
import type { EditorSubtitle } from "../lib/types";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";
import { DEFAULT_SUBTITLE_STYLE, DEFAULT_SUBTITLE_DURATION_MS } from "../constants";
import { generateSubtitleId } from "../hooks/useEditorState";
import { SubtitleBlock } from "./SubtitleBlock";

interface SubtitleTrackProps {
  subtitles: EditorSubtitle[];
  zoom: number;
  totalDurationMs: number;
  playheadMs: number;
  selectedSubtitleIndex: number | null;
  onSelectSubtitle: (index: number | null) => void;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onAddSubtitle: (subtitle: EditorSubtitle) => void;
}

export function SubtitleTrack({
  subtitles,
  zoom,
  totalDurationMs,
  playheadMs,
  selectedSubtitleIndex,
  onSelectSubtitle,
  onUpdateSubtitle,
  onAddSubtitle,
}: SubtitleTrackProps) {
  const totalWidth = msToPixels(totalDurationMs + 2000, zoom);

  const handleTrackDoubleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const clickMs = Math.max(0, Math.round(pixelsToMs(x, zoom)));

      onAddSubtitle({
        id: generateSubtitleId(),
        text: "",
        startMs: clickMs,
        endMs: clickMs + DEFAULT_SUBTITLE_DURATION_MS,
        style: { ...DEFAULT_SUBTITLE_STYLE },
      });
    },
    [zoom, onAddSubtitle],
  );

  const handleAddAtPlayhead = useCallback(() => {
    onAddSubtitle({
      id: generateSubtitleId(),
      text: "",
      startMs: playheadMs,
      endMs: playheadMs + DEFAULT_SUBTITLE_DURATION_MS,
      style: { ...DEFAULT_SUBTITLE_STYLE },
    });
  }, [playheadMs, onAddSubtitle]);

  return (
    <div className="relative">
      {/* Track with blocks */}
      <div
        className="relative h-8 bg-gray-100"
        style={{ width: totalWidth }}
        onDoubleClick={handleTrackDoubleClick}
      >
        {/* Track label */}
        <div className="pointer-events-none absolute -left-0 top-0 z-10 flex h-full items-center">
          <span className="rounded-r bg-gray-200 px-1.5 py-0.5 text-[9px] font-medium text-gray-500">
            자막
          </span>
        </div>

        {/* Add button */}
        <div className="pointer-events-auto absolute right-2 top-0 z-10 flex h-full items-center">
          <button
            type="button"
            onClick={handleAddAtPlayhead}
            className="rounded bg-gray-300 px-1.5 py-0.5 text-[9px] font-medium text-gray-700 transition-colors hover:bg-gray-400 hover:text-white"
          >
            + 자막
          </button>
        </div>

        {/* Subtitle blocks */}
        {subtitles.map((sub, index) => (
          <SubtitleBlock
            key={sub.id}
            subtitle={sub}
            index={index}
            zoom={zoom}
            isSelected={selectedSubtitleIndex === index}
            onSelect={() => onSelectSubtitle(index)}
            onUpdate={onUpdateSubtitle}
          />
        ))}
      </div>
    </div>
  );
}
