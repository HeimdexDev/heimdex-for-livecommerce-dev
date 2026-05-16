"use client";

import { useCallback } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  horizontalListSortingStrategy,
} from "@dnd-kit/sortable";
import type { EditorClip } from "../lib/types";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";
import { ClipBlock } from "./ClipBlock";

interface ClipTrackProps {
  clips: EditorClip[];
  zoom: number;
  selectedClipIndex: number | null;
  totalDurationMs: number;
  onSelectClip: (index: number | null) => void;
  onTrimClip: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onReorderClips: (fromIndex: number, toIndex: number) => void;
  onSeek: (ms: number) => void;
}

export function ClipTrack({
  clips,
  zoom,
  selectedClipIndex,
  totalDurationMs,
  onSelectClip,
  onTrimClip,
  onReorderClips,
  onSeek,
}: ClipTrackProps) {
  const totalWidth = msToPixels(totalDurationMs + 2000, zoom);

  // Require 8px of movement before starting a drag (so clicks still work for select)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const fromIndex = clips.findIndex((c) => c.id === active.id);
      const toIndex = clips.findIndex((c) => c.id === over.id);
      if (fromIndex !== -1 && toIndex !== -1) {
        onReorderClips(fromIndex, toIndex);
      }
    },
    [clips, onReorderClips],
  );

  const handleTrackClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const ms = pixelsToMs(x, zoom);
      onSeek(Math.max(0, Math.round(ms)));
      onSelectClip(null);
    },
    [zoom, onSeek, onSelectClip],
  );

  const sortableIds = clips.map((c) => c.id);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={sortableIds} strategy={horizontalListSortingStrategy}>
        <div
          className="relative h-12 bg-grayscale-800/50"
          style={{ width: totalWidth }}
          onClick={handleTrackClick}
        >
          {/* Track label */}
          <div className="pointer-events-none absolute -left-0 top-0 z-10 flex h-full items-center">
            <span className="rounded-r bg-grayscale-800/60 px-1.5 py-0.5 text-[9px] font-medium text-grayscale-400">
              VIDEO
            </span>
          </div>

          {/* Sortable clip blocks */}
          {clips.map((clip, index) => (
            <ClipBlock
              key={clip.id}
              clip={clip}
              index={index}
              zoom={zoom}
              isSelected={selectedClipIndex === index}
              onSelect={() => onSelectClip(index)}
              onTrim={onTrimClip}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
