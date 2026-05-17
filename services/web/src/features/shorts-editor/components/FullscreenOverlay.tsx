"use client";

// figma: 1713:275105  (cache: .figma-cache/1713-275105_phase5_editor-5.api.json)
// node-name: 2-5.d 쇼츠 편집(전체보기) · spec: position=fixed inset-0 viewport
// 전체, LNB/GNB 위 덮음, iPhone mockup 352×626, 우상단 lucide X + ESC 닫기

import { useEffect } from "react";
import { X } from "lucide-react";
import { PreviewPanel } from "./PreviewPanel";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";

interface FullscreenOverlayProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  overlays?: EditorOverlay[];
  selectedOverlayId?: string | null;
  onSelectOverlay?: (id: string | null) => void;
  onUpdateOverlay?: (id: string, updates: Partial<EditorOverlay>) => void;
  onRemoveOverlay?: (id: string) => void;
  onRemoveSubtitle?: (index: number) => void;
  playheadMs: number;
  isPlaying: boolean;
  totalDurationMs: number;
  selectedSubtitleIndex: number | null;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
  onSelectSubtitle: (index: number | null) => void;
  onUpdateSubtitlePosition: (index: number, positionX: number, positionY: number) => void;
  onUpdateSubtitleFontSize: (index: number, fontSizePx: number) => void;
  onClose: () => void;
}

export function FullscreenOverlay({ onClose, ...previewProps }: FullscreenOverlayProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="쇼츠 미리보기 전체보기"
      className="fixed inset-0 z-50 flex items-center justify-center bg-grayscale-10"
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="전체보기 닫기"
        className="absolute right-6 top-6 flex h-10 w-10 items-center justify-center rounded-full text-grayscale-700 transition-colors hover:bg-grayscale-100"
      >
        <X className="h-5 w-5" />
      </button>
      <PreviewPanel {...previewProps} fullscreen />
    </div>
  );
}
