"use client";

// figma: 1713:271669  (cache: .figma-cache/1713-271669_phase5_editor-1.api.json)
// node-name: Subtitle Block · spec: Block 자막 미리보기 fs=10 fw=500 → text-[10px] font-medium
import { useCallback, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import type { EditorSubtitle } from "../lib/types";
import { msToPixels, pixelsToMs } from "../lib/timeline-math";

interface SubtitleBlockProps {
  subtitle: EditorSubtitle;
  index: number;
  zoom: number;
  isSelected: boolean;
  onSelect: () => void;
  onUpdate: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
}

export function SubtitleBlock({
  subtitle,
  index,
  zoom,
  isSelected,
  onSelect,
  onUpdate,
}: SubtitleBlockProps) {
  const leftPx = msToPixels(subtitle.startMs, zoom);
  const widthPx = msToPixels(subtitle.endMs - subtitle.startMs, zoom);
  const draggingRef = useRef<"move" | "start" | "end" | null>(null);
  const startXRef = useRef(0);
  const startValuesRef = useRef({ startMs: 0, endMs: 0 });

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      if (!draggingRef.current) return;
      const dx = e.clientX - startXRef.current;
      const deltaMs = pixelsToMs(dx, zoom);
      const { startMs, endMs } = startValuesRef.current;

      if (draggingRef.current === "move") {
        const newStart = Math.max(0, Math.round(startMs + deltaMs));
        const duration = endMs - startMs;
        onUpdate(index, { startMs: newStart, endMs: newStart + duration });
      } else if (draggingRef.current === "start") {
        const newStart = Math.max(0, Math.round(startMs + deltaMs));
        if (newStart < endMs - 100) {
          onUpdate(index, { startMs: newStart });
        }
      } else if (draggingRef.current === "end") {
        const newEnd = Math.max(startMs + 100, Math.round(endMs + deltaMs));
        onUpdate(index, { endMs: newEnd });
      }
    },
    [index, zoom, onUpdate],
  );

  const onPointerUp = useCallback(
    (e: PointerEvent) => {
      draggingRef.current = null;
      (e.target as HTMLElement)?.releasePointerCapture?.(e.pointerId);
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    },
    [onPointerMove],
  );

  const handlePointerDown = useCallback(
    (mode: "move" | "start" | "end") => (e: React.PointerEvent) => {
      e.stopPropagation();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      draggingRef.current = mode;
      startXRef.current = e.clientX;
      startValuesRef.current = { startMs: subtitle.startMs, endMs: subtitle.endMs };
      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    },
    [subtitle.startMs, subtitle.endMs, onPointerMove, onPointerUp],
  );

  useEffect(() => {
    return () => {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    };
  }, [onPointerMove, onPointerUp]);

  return (
    <div
      className={cn(
        "group absolute bottom-1 top-1 flex items-center overflow-hidden rounded border",
        isSelected
          ? "z-10 border-heimdex-navy-500 bg-white ring-1 ring-heimdex-navy-500"
          : "border-grayscale-200 bg-white hover:border-grayscale-300",
      )}
      style={{ left: leftPx, width: Math.max(widthPx, 8) }}
      onClick={(e) => { e.stopPropagation(); onSelect(); }}
    >
      {/* Left resize handle */}
      <div
        className="absolute bottom-0 left-0 top-0 z-20 w-1.5 cursor-col-resize bg-grayscale-300 opacity-0 group-hover:opacity-100"
        onPointerDown={handlePointerDown("start")}
      />

      {/* Draggable body */}
      <div
        className="flex-1 min-w-0 px-1.5 cursor-grab active:cursor-grabbing select-none"
        onPointerDown={handlePointerDown("move")}
      >
        {widthPx > 30 && (
          <p className="truncate text-[10px] font-medium text-grayscale-800">
            {subtitle.text || "자막"}
          </p>
        )}
      </div>

      {/* Right resize handle */}
      <div
        className="absolute bottom-0 right-0 top-0 z-20 w-1.5 cursor-col-resize bg-grayscale-300 opacity-0 group-hover:opacity-100"
        onPointerDown={handlePointerDown("end")}
      />
    </div>
  );
}
