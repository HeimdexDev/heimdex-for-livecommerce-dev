"use client";

// figma: 1669:48897 (default) / 1669:48312 (compressed) — timeline shell
// figma: 1669:153949 (toolbar row) — trash + timecode • transport • controls • zoom
import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import {
  Maximize,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  Trash2,
  Volume2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import { msToPixels, formatVideoTimestampHMS } from "../lib/timeline-math";
import { TimelineRuler } from "./TimelineRuler";
import { ClipTrack } from "./ClipTrack";
import { SubtitleTrack } from "./SubtitleTrack";
import { PlayheadCursor } from "./PlayheadCursor";
import { TimelineZoomControl } from "./TimelineZoomControl";

interface TimelinePanelProps {
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  zoom: number;
  playheadMs: number;
  isPlaying: boolean;
  totalDurationMs: number;
  selectedClipIndex: number | null;
  selectedSubtitleIndex: number | null;
  onSelectClip: (index: number | null) => void;
  onSelectSubtitle: (index: number | null) => void;
  onTrimClip: (index: number, trimStartMs?: number, trimEndMs?: number) => void;
  onReorderClips: (fromIndex: number, toIndex: number) => void;
  onUpdateSubtitle: (index: number, updates: Partial<Omit<EditorSubtitle, "id">>) => void;
  onAddSubtitle: (subtitle: EditorSubtitle) => void;
  onRemoveClip: (index: number) => void;
  onRemoveSubtitle: (index: number) => void;
  onTogglePlay: () => void;
  onSeek: (ms: number) => void;
  onZoomChange: (zoom: number) => void;
  // playback rate toggle (1.0 ↔ 1.5). Optional so existing tests
  // and storybook callers don't need updating.
  playbackRate?: number;
  onPlaybackRateChange?: (rate: number) => void;
  // figma: 1670:185907 — volume + maximize controls
  volume?: number;
  onVolumeChange?: (volume: number) => void;
  onToggleFullscreen?: () => void;
}

// figma: 1669:153949 — toolbar buttons are 32×32 r-8 bg neutral-50.
const PILL_BUTTON =
  "flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-neutral-h-50 text-neutral-h-800 transition-colors hover:bg-neutral-h-100 disabled:cursor-not-allowed disabled:opacity-30";

const PLAYBACK_OPTIONS = [2.0, 1.5, 1.0] as const;

// figma: 1669:154051 — vertical 2.0 / 1.5 / 1.0 menu, active option gets a
// neutral/200 pill behind it.
function SpeedPopover({
  rate,
  onChange,
}: {
  rate: number;
  onChange?: (rate: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => onChange && setOpen((v) => !v)}
        disabled={!onChange}
        aria-label={`재생 속도 ${rate.toFixed(1)}x`}
        className="flex h-8 items-center justify-center rounded-[8px] bg-neutral-h-50 px-[10px] py-[2px] text-[14px] font-semibold tracking-[-0.35px] text-neutral-h-800 transition-colors hover:bg-neutral-h-100 disabled:cursor-not-allowed disabled:opacity-30"
      >
        {rate.toFixed(1)}x
      </button>
      {open && (
        <div className="absolute bottom-full left-1/2 z-40 mb-2 flex -translate-x-1/2 flex-col items-center gap-[10px] rounded-[6px] bg-neutral-h-50 p-[6px] shadow-dialog">
          {PLAYBACK_OPTIONS.map((r) => {
            const selected = Math.abs(r - rate) < 0.01;
            return (
              <button
                key={r}
                type="button"
                onClick={() => {
                  onChange?.(r);
                  setOpen(false);
                }}
                className={cn(
                  "flex items-center justify-center rounded-[4px] px-1 text-[14px] font-semibold tracking-[-0.35px] text-neutral-h-800",
                  selected && "bg-neutral-h-200",
                )}
              >
                {r.toFixed(1)}x
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// figma: 1669:154040 — vertical slider popover, ~100×14 surface with -90deg
// rotated range input so drag-up = volume-up.
function VolumePopover({
  volume,
  onChange,
}: {
  volume: number;
  onChange?: (volume: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => onChange && setOpen((v) => !v)}
        disabled={!onChange}
        aria-label={`볼륨 ${Math.round(volume * 100)}%`}
        className={PILL_BUTTON}
      >
        <Volume2 className="h-5 w-5" strokeWidth={1.5} />
      </button>
      {open && (
        <div className="absolute bottom-full left-1/2 z-40 mb-2 flex h-[112px] w-[28px] -translate-x-1/2 items-center justify-center rounded-[4px] bg-neutral-h-50 px-[9px] py-[2px] shadow-dialog">
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={volume}
            onChange={(e) => onChange?.(Number(e.target.value))}
            aria-label={`볼륨 ${Math.round(volume * 100)}%`}
            className="h-[2px] w-[88px] -rotate-90 cursor-pointer accent-grayscale-800"
          />
        </div>
      )}
    </div>
  );
}


export function TimelinePanel({
  clips,
  subtitles,
  zoom,
  playheadMs,
  isPlaying,
  totalDurationMs,
  selectedClipIndex,
  selectedSubtitleIndex,
  onSelectClip,
  onSelectSubtitle,
  onTrimClip,
  onReorderClips,
  onUpdateSubtitle,
  onAddSubtitle,
  onRemoveClip,
  onRemoveSubtitle,
  onTogglePlay,
  onSeek,
  onZoomChange,
  playbackRate = 1.0,
  onPlaybackRateChange,
  volume = 1.0,
  onVolumeChange,
  onToggleFullscreen,
}: TimelinePanelProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);

  const SEEK_TOLERANCE_MS = 100;

  // Clip-boundary timestamps (sorted, deduped) for transport jump-to-prev/next.
  const boundaries = useMemo(() => {
    const set = new Set<number>([0, totalDurationMs]);
    for (const clip of clips) set.add(clip.timelineStartMs);
    return Array.from(set).sort((a, b) => a - b);
  }, [clips, totalDurationMs]);

  const handleSkipPrev = useCallback(() => {
    const target = [...boundaries].reverse().find((b) => b < playheadMs - SEEK_TOLERANCE_MS) ?? 0;
    onSeek(target);
  }, [boundaries, playheadMs, onSeek]);

  const handleSkipNext = useCallback(() => {
    const target = boundaries.find((b) => b > playheadMs + SEEK_TOLERANCE_MS) ?? totalDurationMs;
    onSeek(target);
  }, [boundaries, playheadMs, totalDurationMs, onSeek]);

  const hasSelection = selectedClipIndex != null || selectedSubtitleIndex != null;
  const handleDeleteSelection = useCallback(() => {
    if (selectedClipIndex != null) onRemoveClip(selectedClipIndex);
    else if (selectedSubtitleIndex != null) onRemoveSubtitle(selectedSubtitleIndex);
  }, [selectedClipIndex, selectedSubtitleIndex, onRemoveClip, onRemoveSubtitle]);

  // Auto-scroll to follow playhead during playback
  useEffect(() => {
    if (!isPlaying || !scrollContainerRef.current) return;

    const container = scrollContainerRef.current;
    const playheadPx = msToPixels(playheadMs, zoom);
    const containerWidth = container.clientWidth;
    const scrollLeft = container.scrollLeft;

    if (playheadPx > scrollLeft + containerWidth * 0.8) {
      container.scrollLeft = playheadPx - containerWidth * 0.3;
    }
    if (playheadPx < scrollLeft) {
      container.scrollLeft = Math.max(0, playheadPx - 20);
    }
  }, [playheadMs, isPlaying, zoom]);

  // figma: 1669:154010 (펼침) / 1669:49002 (접힘) — zoom ≥ 100 일 때 자막 트랙 펼침
  const isSubtitleExpanded = zoom >= 100;
  // playhead spans ruler (24px) + clip track (48px) + subtitle track (32 또는 48) + padding
  const trackHeight = 88 + (isSubtitleExpanded ? 48 : 32);

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar — figma 1669:153949 (상단바) */}
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-grayscale-100 px-3">
        {/* LEFT cluster: trash icon + divider + playhead/total timecode */}
        <div className="flex w-[304px] shrink-0 items-center gap-3">
          <button
            type="button"
            onClick={handleDeleteSelection}
            disabled={!hasSelection}
            aria-label="선택 항목 삭제"
            className="rounded p-1 text-grayscale-700 transition-colors hover:bg-grayscale-100 hover:text-red-h-500 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <Trash2 className="h-5 w-5" strokeWidth={1.5} />
          </button>
          <div className="h-[26px] w-[2px] bg-grayscale-100" />
          <span className="text-[14px] font-semibold tracking-[-0.35px] text-grayscale-500">
            {formatVideoTimestampHMS(playheadMs)} / {formatVideoTimestampHMS(totalDurationMs)}
          </span>
        </div>

        {/* CENTER cluster: skip-back / play / skip-forward */}
        <div className="flex flex-1 items-center justify-center gap-[10px]">
          <button
            type="button"
            onClick={handleSkipPrev}
            disabled={playheadMs <= SEEK_TOLERANCE_MS}
            aria-label="이전 클립으로"
            className={PILL_BUTTON}
          >
            <SkipBack className="h-5 w-5" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={onTogglePlay}
            disabled={clips.length === 0}
            aria-label={isPlaying ? "일시정지" : "재생"}
            className={PILL_BUTTON}
          >
            {isPlaying ? (
              <Pause className="h-5 w-5" strokeWidth={1.5} />
            ) : (
              <Play className="h-5 w-5" strokeWidth={1.5} />
            )}
          </button>
          <button
            type="button"
            onClick={handleSkipNext}
            disabled={playheadMs >= totalDurationMs - SEEK_TOLERANCE_MS}
            aria-label="다음 클립으로"
            className={PILL_BUTTON}
          >
            <SkipForward className="h-5 w-5" strokeWidth={1.5} />
          </button>
        </div>

        {/* RIGHT cluster: volume popover • speed popover • fullscreen */}
        <div className="flex items-center gap-[10px]">
          <VolumePopover volume={volume} onChange={onVolumeChange} />
          <SpeedPopover rate={playbackRate} onChange={onPlaybackRateChange} />
          {onToggleFullscreen && (
            <button
              type="button"
              onClick={onToggleFullscreen}
              aria-label="전체화면 미리보기"
              className={PILL_BUTTON}
            >
              <Maximize className="h-5 w-5" strokeWidth={1.5} />
            </button>
          )}
        </div>

        {/* FAR RIGHT: zoom slider (figma 1669:122130 — minus + 88px track + plus) */}
        <div className="w-[156px] shrink-0">
          <TimelineZoomControl zoom={zoom} onZoomChange={onZoomChange} />
        </div>
      </div>

      {/* Scrollable timeline area */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-x-auto overflow-y-hidden"
      >
        <div className="relative" style={{ minWidth: "100%" }}>
          {/* Ruler */}
          <TimelineRuler totalDurationMs={totalDurationMs} zoom={zoom} />

          {/* Subtitle track — figma 1669:49003: subtitles row sits ABOVE clips */}
          <SubtitleTrack
            subtitles={subtitles}
            zoom={zoom}
            totalDurationMs={totalDurationMs}
            playheadMs={playheadMs}
            selectedSubtitleIndex={selectedSubtitleIndex}
            onSelectSubtitle={onSelectSubtitle}
            onUpdateSubtitle={onUpdateSubtitle}
            onAddSubtitle={onAddSubtitle}
            expanded={isSubtitleExpanded}
          />

          {/* Clip track — figma 1669:49030: scene row below the subtitle row */}
          <ClipTrack
            clips={clips}
            zoom={zoom}
            selectedClipIndex={selectedClipIndex}
            totalDurationMs={totalDurationMs}
            onSelectClip={onSelectClip}
            onTrimClip={onTrimClip}
            onReorderClips={onReorderClips}
            onSeek={onSeek}
          />

          {/* Playhead cursor — spans ruler + all tracks */}
          <PlayheadCursor
            playheadMs={playheadMs}
            zoom={zoom}
            height={trackHeight}
            onSeek={onSeek}
            showTooltip
          />
        </div>
      </div>
    </div>
  );
}
