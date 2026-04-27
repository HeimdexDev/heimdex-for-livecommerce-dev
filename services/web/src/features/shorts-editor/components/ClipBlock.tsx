"use client";

import { cn } from "@/lib/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { EditorClip } from "../lib/types";
import { msToPixels, getClipDuration, formatTimelineTimestamp } from "../lib/timeline-math";
import { useClipTrim } from "../hooks/useClipTrim";

// Single uniform dark surface; per-clip identity comes from the thumbnail.
const CLIP_BLOCK_BG = "bg-gray-800";

interface ClipBlockProps {
  clip: EditorClip;
  index: number;
  zoom: number;
  isSelected: boolean;
  onSelect: () => void;
  onTrim: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
}

export function ClipBlock({
  clip,
  index,
  zoom,
  isSelected,
  onSelect,
  onTrim,
}: ClipBlockProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: clip.id });

  const { onTrimStartDown, onTrimEndDown } = useClipTrim({
    clip,
    clipIndex: index,
    zoom,
    onTrim,
  });

  const widthPx = msToPixels(getClipDuration(clip), zoom);
  const leftPx = msToPixels(clip.timelineStartMs, zoom);
  const durationSec = (getClipDuration(clip) / 1000).toFixed(1);

  const style: React.CSSProperties = {
    left: leftPx,
    width: Math.max(widthPx, 4),
    transform: CSS.Translate.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "group absolute bottom-1 top-1 flex cursor-pointer overflow-hidden rounded-md border transition-shadow",
        isSelected
          ? "z-10 border-white shadow-lg ring-1 ring-white"
          : "border-white/10 hover:border-white/30",
        isDragging && "z-20 shadow-xl",
        CLIP_BLOCK_BG,
      )}
      style={style}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(); }}
    >
      {/* Left trim handle */}
      <div
        className="absolute left-0 top-0 bottom-0 z-20 w-2 cursor-col-resize opacity-0 transition-opacity group-hover:opacity-100 hover:!opacity-100 bg-white/40"
        onPointerDown={onTrimStartDown}
      >
        <div className="absolute left-0.5 top-1/2 -translate-y-1/2 h-6 w-0.5 rounded-full bg-white" />
      </div>

      {/* Drag handle area (center content) */}
      <div
        className="flex-1 min-w-0 flex items-center gap-1.5 px-2 overflow-hidden cursor-grab active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        {/* Thumbnail (only show if clip is wide enough) */}
        {widthPx > 60 && (
          <div className="h-8 w-12 flex-shrink-0 overflow-hidden rounded-sm pointer-events-none">
            <SceneThumbnail
              videoId={clip.videoId}
              sceneId={clip.sceneId}
              agentAvailable={clip.sourceType !== "gdrive"}
              className="h-full w-full object-cover"
            />
          </div>
        )}

        {/* Label */}
        {widthPx > 40 && (
          <div className="min-w-0 flex-1 pointer-events-none">
            {clip.label && widthPx > 80 ? (
              <>
                <p className="truncate text-[10px] font-medium leading-tight text-white">
                  {clip.label}
                </p>
                <p className="truncate text-[9px] leading-tight text-white/70">
                  {durationSec}s
                </p>
              </>
            ) : (
              <>
                <p className="truncate text-[10px] font-medium leading-tight text-white">
                  {durationSec}s
                </p>
                {widthPx > 100 && (
                  <p className="truncate text-[9px] leading-tight text-white/70">
                    {formatTimelineTimestamp(clip.trimStartMs)}
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Right trim handle */}
      <div
        className="absolute right-0 top-0 bottom-0 z-20 w-2 cursor-col-resize opacity-0 transition-opacity group-hover:opacity-100 hover:!opacity-100 bg-white/40"
        onPointerDown={onTrimEndDown}
      >
        <div className="absolute right-0.5 top-1/2 -translate-y-1/2 h-6 w-0.5 rounded-full bg-white" />
      </div>
    </div>
  );
}
