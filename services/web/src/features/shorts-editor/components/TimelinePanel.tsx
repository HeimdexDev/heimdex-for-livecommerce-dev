"use client";

// figma: 1713:271669  (cache: .figma-cache/1713-271669_phase5_editor-1.api.json)
// node-name: Timeline 상단바 · spec: h=32 padL/R=12, 타임코드 fs=14 fw=600 → h-8 / text-sm font-semibold
import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import type { EditorClip, EditorSubtitle } from "../lib/types";
import { msToPixels, formatTimelineTimestamp } from "../lib/timeline-math";
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

// figma: 1670:185907 + 1670:186278 — 배속 토글 1.0 → 1.5 → 2.0 → 1.0
const PLAYBACK_RATES = [1.0, 1.5, 2.0] as const;

function nextPlaybackRate(current: number): number {
  const idx = PLAYBACK_RATES.findIndex((r) => Math.abs(r - current) < 0.01);
  return PLAYBACK_RATES[(idx + 1) % PLAYBACK_RATES.length] ?? 1.0;
}

function parseTimestampInput(value: string): number | null {
  const parts = value.split(":").map((p) => parseInt(p, 10));
  if (parts.some(isNaN)) return null;
  if (parts.length === 3) return (parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000;
  if (parts.length === 2) return (parts[0] * 60 + parts[1]) * 1000;
  if (parts.length === 1) return parts[0] * 1000;
  return null;
}

function TimestampInput({ playheadMs, onSeek }: { playheadMs: number; onSeek: (ms: number) => void }) {
  const [editing, setEditing] = useState(false);
  const [inputValue, setInputValue] = useState("");

  const displayValue = formatTimelineTimestamp(playheadMs);

  const handleCommit = () => {
    const ms = parseTimestampInput(inputValue);
    if (ms != null && ms >= 0) {
      onSeek(ms);
    }
    setEditing(false);
  };

  if (editing) {
    return (
      <input
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onBlur={handleCommit}
        onKeyDown={(e) => {
          if (e.key === "Enter") handleCommit();
          if (e.key === "Escape") setEditing(false);
        }}
        autoFocus
        className="w-20 rounded border border-heimdex-navy-400 bg-white px-1.5 py-0.5 text-center text-sm font-semibold text-grayscale-800 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        setInputValue(displayValue);
        setEditing(true);
      }}
      className="w-20 rounded border border-grayscale-200 bg-white px-1.5 py-0.5 text-center text-sm font-semibold text-grayscale-500 hover:border-heimdex-navy-400 hover:text-grayscale-800"
    >
      {displayValue}
    </button>
  );
}

function TrashIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
    </svg>
  );
}

function SkipPrevIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 6h2v12H6V6zm3.5 6L18 6v12l-8.5-6z" />
    </svg>
  );
}

function SkipNextIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 18l8.5-6L6 6v12zM16 6h2v12h-2V6z" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function VolumeIcon() {
  // lucide/volume-2
  return (
    <svg className="h-4 w-4 text-grayscale-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M11 5L6 9H2v6h4l5 4V5z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.54 8.46a5 5 0 010 7.07M19.07 4.93a10 10 0 010 14.14" />
    </svg>
  );
}

function MaximizeIcon() {
  // lucide/maximize
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
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
      {/* Toolbar — trash + timestamp (left), transport (center), zoom (right) */}
      <div className="grid h-8 flex-shrink-0 grid-cols-3 items-center border-b border-gray-300 bg-gray-100 px-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleDeleteSelection}
            disabled={!hasSelection}
            aria-label="선택 항목 삭제"
            className="rounded p-1 text-gray-500 transition-colors hover:bg-gray-200 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <TrashIcon />
          </button>
          <TimestampInput playheadMs={playheadMs} onSeek={onSeek} />
          <span className="text-sm font-semibold text-grayscale-500">
            / {formatTimelineTimestamp(totalDurationMs)}
          </span>
        </div>

        <div className="flex items-center justify-center gap-1">
          <button
            type="button"
            onClick={handleSkipPrev}
            disabled={playheadMs <= SEEK_TOLERANCE_MS}
            aria-label="이전 클립으로"
            className="rounded p-1 text-gray-500 transition-colors hover:bg-gray-200 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <SkipPrevIcon />
          </button>
          <button
            type="button"
            onClick={onTogglePlay}
            disabled={clips.length === 0}
            aria-label={isPlaying ? "일시정지" : "재생"}
            className="rounded p-1 text-gray-700 transition-colors hover:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-30"
          >
            {isPlaying ? <PauseIcon /> : <PlayIcon />}
          </button>
          <button
            type="button"
            onClick={handleSkipNext}
            disabled={playheadMs >= totalDurationMs - SEEK_TOLERANCE_MS}
            aria-label="다음 클립으로"
            className="rounded p-1 text-gray-500 transition-colors hover:bg-gray-200 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <SkipNextIcon />
          </button>
        </div>

        <div className="flex items-center justify-end gap-1">
          {/* figma: 1670:185907 — volume slider (lucide/volume-2 + 88px slider) */}
          {onVolumeChange && (
            <div className="mr-1 flex items-center gap-1">
              <VolumeIcon />
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={volume}
                onChange={(e) => onVolumeChange(Number(e.target.value))}
                aria-label={`볼륨 ${Math.round(volume * 100)}%`}
                className="h-1 w-16 cursor-pointer accent-grayscale-800"
              />
            </div>
          )}
          {/* figma: 1670:185907 + 1670:186278 — 배속 토글 1.0 → 1.5 → 2.0 cycle */}
          <button
            type="button"
            onClick={() => onPlaybackRateChange?.(nextPlaybackRate(playbackRate))}
            disabled={!onPlaybackRateChange}
            aria-label={`재생속도 ${playbackRate.toFixed(1)}x (클릭하여 변경)`}
            className="mr-1 rounded px-1.5 py-0.5 text-sm font-semibold text-grayscale-700 transition-colors hover:bg-gray-200 disabled:cursor-not-allowed disabled:opacity-30"
          >
            {playbackRate.toFixed(1)}x
          </button>
          {/* figma: 1670:185907 + 1669:48897 — 전체화면 트리거 */}
          {onToggleFullscreen && (
            <button
              type="button"
              onClick={onToggleFullscreen}
              aria-label="전체화면 미리보기"
              className="mr-1 rounded p-1 text-grayscale-700 transition-colors hover:bg-gray-200"
            >
              <MaximizeIcon />
            </button>
          )}
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
