"use client";

// figma: 1669:48897 (default) / 1669:48312 (compressed) — timeline shell
// figma: 1669:153949 (toolbar row) — trash + timecode • transport • controls • zoom
import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import { createPortal } from "react-dom";
import { Maximize, Pause, Trash2, Volume2 } from "lucide-react";
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
  const buttonRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => onChange && setOpen((v) => !v)}
        disabled={!onChange}
        aria-label={`재생 속도 ${rate.toFixed(1)}x`}
        aria-expanded={open}
        className="flex h-8 items-center justify-center rounded-[8px] bg-neutral-h-50 px-[10px] py-[2px] text-[14px] font-semibold tracking-[-0.35px] text-neutral-h-800 transition-colors hover:bg-neutral-h-100 disabled:cursor-not-allowed disabled:opacity-30"
      >
        {rate.toFixed(1)}x
      </button>
      {open && (
        // Portalled so the popover escapes the timeline card's
        // overflow-hidden chrome. Anchored above the trigger via
        // AnchoredAbovePopover so it can still pop up out of the
        // editor's bottom toolbar.
        <AnchoredAbovePopover anchorRef={buttonRef} onClose={() => setOpen(false)}>
          <div className="flex flex-col items-center gap-[10px] rounded-[6px] bg-neutral-h-50 p-[6px] shadow-dialog">
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
        </AnchoredAbovePopover>
      )}
    </>
  );
}

// Portal-based popover that anchors above the supplied trigger element.
// Lives here (vs in a shared primitive) because only TimelinePanel's
// speed + volume popovers need this exact "above the trigger" placement
// and they both share the same overflow-clip issue with the bottom
// editor card.
function AnchoredAbovePopover({
  anchorRef,
  onClose,
  children,
}: {
  anchorRef: React.RefObject<HTMLElement>;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: -9999, left: -9999 });
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Position the popover above the anchor, centred horizontally over it.
  // The actual width is content-driven, so we render to the DOM first,
  // measure, then recompute — handles both the speed list (auto width)
  // and the vertical volume slider (28px wide).
  useEffect(() => {
    const place = () => {
      const anchor = anchorRef.current;
      const popover = popoverRef.current;
      if (!anchor || !popover) return;
      const arect = anchor.getBoundingClientRect();
      const prect = popover.getBoundingClientRect();
      let top = arect.top - prect.height - 8;
      let left = arect.left + arect.width / 2 - prect.width / 2;
      const margin = 8;
      if (top < margin) top = margin;
      if (left < margin) left = margin;
      if (left + prect.width > window.innerWidth - margin) {
        left = window.innerWidth - prect.width - margin;
      }
      setPos({ top, left });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [anchorRef]);

  useEffect(() => {
    function handle(e: MouseEvent) {
      const target = e.target as Node;
      if (popoverRef.current && popoverRef.current.contains(target)) return;
      if (anchorRef.current && anchorRef.current.contains(target)) return;
      onClose();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [anchorRef, onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      ref={popoverRef}
      style={{ position: "fixed", top: pos.top, left: pos.left, zIndex: 50 }}
    >
      {children}
    </div>,
    document.body,
  );
}

// figma export `2-5.a 쇼츠 편집(자막 선택)/상품 선택/lucide/play.svg` —
// solid filled triangle (no stroke). Replaces lucide-react's hollow
// Play so the transport cluster matches the figma spec exactly.
function PlayIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M4.16675 4.16716C4.16666 3.8739 4.24395 3.58582 4.39082 3.33199C4.53768 3.07816 4.74892 2.86757 5.00321 2.72149C5.25749 2.57541 5.54582 2.49901 5.83907 2.50001C6.13233 2.50101 6.42013 2.57936 6.67341 2.72716L16.6709 8.55883C16.9232 8.70523 17.1327 8.91528 17.2784 9.168C17.4241 9.42071 17.5009 9.70724 17.5011 9.99894C17.5014 10.2906 17.4251 10.5773 17.2798 10.8303C17.1346 11.0832 16.9255 11.2937 16.6734 11.4405L6.67341 17.2738C6.42013 17.4216 6.13233 17.5 5.83907 17.501C5.54582 17.502 5.25749 17.4256 5.00321 17.2795C4.74892 17.1334 4.53768 16.9228 4.39082 16.669C4.24395 16.4152 4.16666 16.1271 4.16675 15.8338V4.16716Z" />
    </svg>
  );
}

// figma export `... skip-back.svg` — left triangle + leading vertical
// bar. Fill + stroke share currentColor so the parent can recolor it
// (disabled state etc.) with the existing PILL_BUTTON text classes.
function SkipBackIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="1.66667"
      strokeLinecap="round"
      strokeLinejoin="round"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M2.5 16.6664V3.33302" fill="none" />
      <path d="M14.9758 3.57052C15.2287 3.41878 15.5174 3.33686 15.8123 3.33314C16.1072 3.32942 16.3978 3.40403 16.6545 3.54934C16.9112 3.69466 17.1247 3.90548 17.2732 4.16029C17.4217 4.41509 17.5 4.70475 17.5 4.99969V14.9997C17.5 15.2946 17.4217 15.5843 17.2732 15.8391C17.1247 16.0939 16.9112 16.3047 16.6545 16.45C16.3978 16.5954 16.1072 16.67 15.8123 16.6662C15.5174 16.6625 15.2287 16.5806 14.9758 16.4289L6.645 11.4305C6.39769 11.2828 6.19291 11.0734 6.05062 10.8229C5.90834 10.5724 5.83342 10.2893 5.83317 10.0012C5.83291 9.71314 5.90734 9.42991 6.04919 9.17916C6.19103 8.92842 6.39545 8.71872 6.6425 8.57052L14.9758 3.57052Z" />
    </svg>
  );
}

// figma export `... skip-forward.svg` — mirror of skip-back: right
// triangle + trailing vertical bar.
function SkipForwardIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="1.66667"
      strokeLinecap="round"
      strokeLinejoin="round"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <path d="M17.5 3.33302V16.6664" fill="none" />
      <path d="M5.02417 3.57052C4.77126 3.41878 4.48261 3.33686 4.18769 3.33314C3.89278 3.32942 3.60216 3.40403 3.3455 3.54934C3.08884 3.69466 2.87534 3.90548 2.7268 4.16029C2.57826 4.41509 2.5 4.70475 2.5 4.99969V14.9997C2.5 15.2946 2.57826 15.5843 2.7268 15.8391C2.87534 16.0939 3.08884 16.3047 3.3455 16.45C3.60216 16.5954 3.89278 16.67 4.18769 16.6662C4.48261 16.6625 4.77126 16.5806 5.02417 16.4289L13.355 11.4305C13.6023 11.2828 13.8071 11.0734 13.9494 10.8229C14.0917 10.5724 14.1666 10.2893 14.1668 10.0012C14.1671 9.71314 14.0927 9.42991 13.9508 9.17916C13.809 8.92842 13.6045 8.71872 13.3575 8.57052L5.02417 3.57052Z" />
    </svg>
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
  const buttonRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => onChange && setOpen((v) => !v)}
        disabled={!onChange}
        aria-label={`볼륨 ${Math.round(volume * 100)}%`}
        aria-expanded={open}
        className={PILL_BUTTON}
      >
        <Volume2 className="h-5 w-5" strokeWidth={1.5} />
      </button>
      {open && (
        // Portalled so the vertical slider doesn't get clipped by the
        // timeline card's overflow-hidden chrome; matches SpeedPopover's
        // anchoring approach.
        <AnchoredAbovePopover anchorRef={buttonRef} onClose={() => setOpen(false)}>
          <div className="flex h-[112px] w-[28px] items-center justify-center rounded-[4px] bg-neutral-h-50 px-[9px] py-[2px] shadow-dialog">
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
        </AnchoredAbovePopover>
      )}
    </>
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

  // Subtitle track height is now locked to 48px regardless of zoom
  // (2026-05-18 review — operators expected the row's vertical extent
  // to stay constant while zoom only changed horizontal span). The
  // ``expanded`` prop on SubtitleTrack is no longer load-bearing.
  const isSubtitleExpanded = true;
  // playhead spans ruler (24px) + clip track (48px) + subtitle track (48px) + padding
  const trackHeight = 88 + 48;

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
            <SkipBackIcon className="h-5 w-5" />
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
              <PlayIcon className="h-5 w-5" />
            )}
          </button>
          <button
            type="button"
            onClick={handleSkipNext}
            disabled={playheadMs >= totalDurationMs - SEEK_TOLERANCE_MS}
            aria-label="다음 클립으로"
            className={PILL_BUTTON}
          >
            <SkipForwardIcon className="h-5 w-5" />
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
          {/* Ruler — clicking anywhere on the ruler seeks the playhead
              to that timecode. Reuses the same onSeek the playhead drag
              already calls, so audio + preview sync paths converge on
              one path. */}
          <TimelineRuler
            totalDurationMs={totalDurationMs}
            zoom={zoom}
            onSeek={onSeek}
          />

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
