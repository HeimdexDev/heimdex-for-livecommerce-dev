"use client";

import { useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { getCloudPlaybackUrl } from "@/lib/agent";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { reasonChipsFor, type ReasonChip } from "../lib/reason-chip-copy";
import type { AutoClipResponse } from "@/lib/types";

interface AutoClipCardProps {
  index: number;
  clip: AutoClipResponse;
  videoId: string;
}

function formatHMS(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatSeconds(ms: number): string {
  return `${Math.round(ms / 1000)}초`;
}

const CHIP_VARIANT_STYLES: Record<ReasonChip["variant"], string> = {
  success: "bg-emerald-50 text-emerald-700 border border-emerald-100",
  info: "bg-indigo-50 text-indigo-700 border border-indigo-100",
  neutral: "bg-gray-100 text-gray-700 border border-gray-200",
};

export function AutoClipCard({ index, clip, videoId }: AutoClipCardProps) {
  const { visible, overflow } = reasonChipsFor(clip.reasons, 3);
  const scorePct = Math.round(Math.min(1, Math.max(0, clip.score)) * 100);
  const representativeSceneId = clip.scene_ids[0];
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentMemberIdx, setCurrentMemberIdx] = useState(0);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  // Use the raw proxy URL; we seek client-side to each member's span
  // in turn. getCloudPlaybackUrl accepts a startMs but we override via
  // seeking so passing 0 keeps the URL stable across member jumps.
  const playbackUrl = getCloudPlaybackUrl(videoId, 0);

  // Sequential member playback — plays member 0's span, seeks to
  // member 1's span at its end, and so on. Skips the gap time between
  // non-adjacent picks. Total played duration = sum(member durations).
  function handleTimeUpdate() {
    const v = videoRef.current;
    if (!v) return;
    const members = clip.members;
    if (!members.length) return;
    const idx = currentMemberIdx;
    if (idx >= members.length) return;

    const nowMs = v.currentTime * 1000;
    const cur = members[idx];
    if (nowMs >= cur.end_ms) {
      const next = idx + 1;
      if (next < members.length) {
        setCurrentMemberIdx(next);
        // Seek forward (or backward) to the next member's start.
        v.currentTime = members[next].start_ms / 1000;
      } else {
        v.pause();
        setIsPlaying(false);
        setCurrentMemberIdx(0);
      }
    }
  }

  function handleLoadedMetadata() {
    const v = videoRef.current;
    if (!v || !clip.members.length) return;
    // Seek to the first member's span on initial load.
    v.currentTime = clip.members[0].start_ms / 1000;
    setCurrentMemberIdx(0);
  }

  function togglePlay() {
    setIsPlaying((prev) => !prev);
    setCurrentMemberIdx(0);
  }

  return (
    <article
      aria-label={`자동 선택 장면 ${index + 1}`}
      className="flex w-full flex-col overflow-hidden rounded-xl border border-gray-200 bg-white"
    >
      <div className="flex w-full gap-0">
      <div className="w-[180px] flex-shrink-0">
        <button
          type="button"
          onClick={togglePlay}
          aria-label={isPlaying ? "미리보기 닫기" : "클립 미리보기 재생"}
          aria-expanded={isPlaying}
          className="group relative block h-full w-full"
        >
          <SceneThumbnail
            videoId={videoId}
            sceneId={representativeSceneId}
            agentAvailable={true}
            className="aspect-video w-full"
          />
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/0 transition group-hover:bg-black/20">
            <span
              aria-hidden="true"
              className="flex h-10 w-10 items-center justify-center rounded-full bg-white/90 text-indigo-700 opacity-0 shadow transition group-hover:opacity-100"
            >
              {isPlaying ? (
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                  <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                  <path d="M8 5v14l11-7z" />
                </svg>
              )}
            </span>
          </div>
        </button>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-bold text-gray-900">클립 {index + 1}</span>
          <div className="flex items-center gap-1.5">
            <span className="rounded-[2px] bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {formatHMS(clip.start_ms)} - {formatHMS(clip.end_ms)}
            </span>
            <span className="text-xs text-gray-500">{formatSeconds(clip.duration_ms)}</span>
          </div>
        </div>
        <div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-gray-500">매칭 점수</span>
            <span className="text-xs font-medium text-gray-700">{scorePct}%</span>
          </div>
          <div
            className="mt-1 h-1 w-full rounded-full bg-indigo-100"
            aria-hidden="true"
          >
            <div
              className="h-1 rounded-full bg-indigo-500"
              style={{ width: `${scorePct}%` }}
            />
          </div>
        </div>
        {visible.length > 0 && (
          <div className="flex flex-wrap gap-1.5" aria-label="선택 근거">
            {visible.map((chip, i) => (
              <span
                key={`${chip.raw}-${i}`}
                title={chip.raw}
                className={cn(
                  "inline-flex rounded-full px-2 py-0.5 text-[11px] leading-4",
                  CHIP_VARIANT_STYLES[chip.variant],
                )}
              >
                {chip.label}
              </span>
            ))}
            {overflow > 0 && (
              <span className="inline-flex rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] leading-4 text-gray-500">
                +{overflow}
              </span>
            )}
          </div>
        )}
        <div className="mt-auto flex items-center gap-2 text-[11px] text-gray-400">
          <span>{clip.scene_ids.length}개 장면</span>
          <span>·</span>
          <span>{clip.is_continuous ? "연속" : "선별"}</span>
        </div>
      </div>
      </div>
      {isPlaying && (
        <div className="border-t border-gray-200 bg-black">
          <video
            ref={videoRef}
            src={playbackUrl}
            autoPlay
            playsInline
            onLoadedMetadata={handleLoadedMetadata}
            onTimeUpdate={handleTimeUpdate}
            onEnded={() => {
              setIsPlaying(false);
              setCurrentMemberIdx(0);
            }}
            className="aspect-video w-full"
            aria-label={`클립 ${index + 1} 미리보기`}
          >
            브라우저가 비디오 재생을 지원하지 않습니다.
          </video>
          <div className="flex items-center justify-between px-3 py-2 text-xs text-gray-300">
            <span>
              장면 {currentMemberIdx + 1} / {clip.members.length}
            </span>
            <span>{formatSeconds(clip.duration_ms)} 하이라이트</span>
          </div>
        </div>
      )}
    </article>
  );
}
