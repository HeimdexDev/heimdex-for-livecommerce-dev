import { useCallback, useRef, useEffect } from "react";
import type { EditorClip } from "../lib/types";
import { pixelsToMs } from "../lib/timeline-math";

type TrimEdge = "start" | "end";

interface UseClipTrimOptions {
  clip: EditorClip;
  clipIndex: number;
  zoom: number;
  onTrim: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
}

/**
 * Pointer-event based trim handle interaction.
 * Returns onPointerDown handlers for left (start) and right (end) trim handles.
 */
export function useClipTrim({ clip, clipIndex, zoom, onTrim }: UseClipTrimOptions) {
  const startXRef = useRef(0);
  const startValueRef = useRef(0);
  const edgeRef = useRef<TrimEdge>("start");

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      const dx = e.clientX - startXRef.current;
      const deltaMs = pixelsToMs(dx, zoom);
      const newValue = startValueRef.current + deltaMs;

      if (edgeRef.current === "start") {
        onTrim(clipIndex, Math.round(newValue), undefined);
      } else {
        onTrim(clipIndex, undefined, Math.round(newValue));
      }
    },
    [clipIndex, zoom, onTrim],
  );

  const onPointerUp = useCallback(
    (e: PointerEvent) => {
      (e.target as HTMLElement)?.releasePointerCapture?.(e.pointerId);
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    },
    [onPointerMove],
  );

  const createHandleDown = useCallback(
    (edge: TrimEdge) => (e: React.PointerEvent) => {
      e.stopPropagation();
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture(e.pointerId);

      startXRef.current = e.clientX;
      edgeRef.current = edge;
      startValueRef.current = edge === "start" ? clip.trimStartMs : clip.trimEndMs;

      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", onPointerUp);
    },
    [clip.trimStartMs, clip.trimEndMs, onPointerMove, onPointerUp],
  );

  // Cleanup on unmount if drag was in progress
  useEffect(() => {
    return () => {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", onPointerUp);
    };
  }, [onPointerMove, onPointerUp]);

  return {
    onTrimStartDown: createHandleDown("start"),
    onTrimEndDown: createHandleDown("end"),
  };
}
