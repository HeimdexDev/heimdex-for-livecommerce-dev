"use client";

// figma: 1682:187740 — 전체보기 모달
// spec: backdrop bg-[rgba(2,3,20,0.4)] backdrop-blur, centered card bg-white r-20 p-20 gap-10
//       header row: filename 16px semibold + [닫기] secondary
//       phone frame 387×688 r-10 with overlays
//       bottom player row: progress (white track / heimdex-navy fill) + play/skip pills

import { useEffect } from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import type { EditorOverlay } from "../lib/overlay-types";
import { OverlayRenderer } from "./preview/OverlayRenderer";
import { getActiveSubtitles } from "../lib/source-time";
import { formatTimelineTimestamp } from "../lib/timeline-math";
import { resolveFontFamily } from "@/lib/fonts";
import { usePlaybackSync } from "../hooks/usePlaybackSync";

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
  filename?: string;
}

export function FullscreenOverlay({
  clips,
  subtitles,
  overlays = [],
  selectedOverlayId = null,
  onSelectOverlay,
  playheadMs,
  isPlaying,
  totalDurationMs,
  onPlayheadChange,
  onPlayingChange,
  onClose,
  filename,
}: FullscreenOverlayProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const { videoRef, preloadRef, togglePlay, onSeeked, onEnded } = usePlaybackSync({
    clips,
    playheadMs,
    isPlaying,
    onPlayheadChange,
    onPlayingChange,
  });

  const activeSubtitles = getActiveSubtitles(subtitles, playheadMs);
  const progressPct =
    totalDurationMs > 0 ? Math.min(100, (playheadMs / totalDurationMs) * 100) : 0;

  const handleSkipBack = () => onPlayheadChange(Math.max(0, playheadMs - 5000));
  const handleSkipForward = () =>
    onPlayheadChange(Math.min(totalDurationMs, playheadMs + 5000));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="쇼츠 미리보기 전체보기"
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(2,3,20,0.4)] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="flex flex-col items-start gap-[10px] rounded-[20px] bg-white p-5 shadow-[2px_2px_20px_0px_rgba(0,0,0,0.25)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header row — filename + close */}
        <div className="flex w-full items-start justify-between">
          <p className="text-[16px] font-semibold leading-[1.4] tracking-[-0.4px] text-black">
            {filename ?? "쇼츠 미리보기"}
          </p>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 items-center rounded-[8px] border border-neutral-h-500 bg-white px-[10px] py-[6px] text-[12px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10"
          >
            닫기
          </button>
        </div>

        {/* Vertical phone frame — figma 387×688 */}
        <div
          className="relative flex h-[688px] w-[387px] items-end justify-center overflow-hidden rounded-[10px] bg-black"
          onClick={() => onSelectOverlay?.(null)}
        >
          <video
            ref={videoRef}
            className="absolute inset-0 h-full w-full object-cover"
            playsInline
            onSeeked={onSeeked}
            onEnded={onEnded}
          />
          <video ref={preloadRef} className="hidden" preload="auto" muted playsInline />

          {/* Subtitles — center-aligned figma style */}
          {activeSubtitles.map((sub) => (
            <p
              key={sub.id}
              className="pointer-events-none absolute select-none text-center"
              style={{
                left: `${sub.style.positionX * 100}%`,
                top: `${sub.style.positionY * 100}%`,
                transform: "translate(-50%, -50%)",
                fontFamily: resolveFontFamily(sub.style.fontFamily),
                fontSize: `${Math.max(8, sub.style.fontSizePx * 0.55)}px`,
                color: sub.style.fontColor,
                fontWeight: sub.style.fontWeight,
                padding: "2px 6px",
                borderRadius: "2px",
                ...(sub.style.backgroundColor
                  ? {
                      backgroundColor: sub.style.backgroundColor,
                      opacity: sub.style.backgroundOpacity,
                    }
                  : {}),
              }}
            >
              {sub.text}
            </p>
          ))}

          {/* V2 overlays — full styling via OverlayRenderer */}
          {overlays
            .filter((o) => o.startMs <= playheadMs && playheadMs < o.endMs)
            .map((o) => (
              <OverlayRenderer
                key={o.id}
                overlay={o}
                isSelected={selectedOverlayId === o.id}
                onClick={() => onSelectOverlay?.(o.id)}
              />
            ))}

          {/* Bottom transport row — figma 1682:187750 */}
          <div className="relative z-10 flex w-full flex-col gap-3 p-[10px]">
            <div className="relative h-1 w-full bg-white">
              <div
                className="h-full bg-heimdex-navy-500 transition-[width]"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="flex items-center gap-[10px]">
              <button
                type="button"
                onClick={togglePlay}
                aria-label={isPlaying ? "일시정지" : "재생"}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-white",
                  "bg-[rgba(38,38,38,0.5)] hover:bg-[rgba(38,38,38,0.7)]",
                )}
              >
                {isPlaying ? (
                  <Pause className="h-5 w-5" />
                ) : (
                  <Play className="h-5 w-5" />
                )}
              </button>
              <div className="flex h-8 items-center justify-between gap-2 rounded-full bg-[rgba(38,38,38,0.5)] px-2">
                <button
                  type="button"
                  onClick={handleSkipBack}
                  aria-label="5초 뒤로"
                  className="text-white hover:text-white/80"
                >
                  <SkipBack className="h-5 w-5" />
                </button>
                <button
                  type="button"
                  onClick={handleSkipForward}
                  aria-label="5초 앞으로"
                  className="text-white hover:text-white/80"
                >
                  <SkipForward className="h-5 w-5" />
                </button>
              </div>
              <div className="flex h-8 items-center rounded-full bg-[rgba(38,38,38,0.5)] px-2">
                <span className="text-[14px] font-medium leading-[1.4] tracking-[-0.35px] text-white">
                  {formatTimelineTimestamp(playheadMs)} /{" "}
                  {formatTimelineTimestamp(totalDurationMs)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
