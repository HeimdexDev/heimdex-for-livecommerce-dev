"use client";

// figma: 1713:270773 (cache: .figma-cache/1713-270773_phase1_video-detail-overview.api.json)
// Video detail overview — card outer / custom controls / source chip / speaker chip / header.

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SkipBack, SkipForward } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useAgent } from "@/features/search/hooks/useAgent";
import { getVideoScenes, getReprocessStatus, reprocessScenes, patchSceneOverride, resetSceneOverride, getVideoSummary, generateVideoSummary, editVideoSummary, resetVideoSummary } from "@/lib/api/videos";
import { getAgentPlaybackUrl, getAgentThumbnailUrl, getCloudPlaybackUrl, getCloudThumbnailUrl } from "@/lib/agent";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { CopyIcon } from "@/components/icons";
import { formatTimestamp } from "@/lib/api/utils";
import { formatVideoTimestampHMS } from "@/lib/timeline";
import type { VideoScene, VideoScenesResponse, VideoSummaryResponse, ReprocessJobResponse, ReprocessParams } from "@/lib/types";
import { cn } from "@/lib/utils";
import { OpenInDriveButton } from "@/components/OpenInDriveButton";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";
import { InlineEditField } from "./InlineEditField";
import { TagEditor } from "./TagEditor";
import { ReprocessDialog } from "./ReprocessDialog";
import { BlurRunDialog } from "@/features/blur/components/BlurRunDialog";
import { useBlurJobsForFile } from "@/features/blur/hooks/useBlurJob";
import { createBlurJob, type BlurCategory } from "@/lib/api/blur";
import { SceneGroupCard } from "./SceneGroupCard";
import { VideoPeoplePanel } from "./VideoPeoplePanel";
import { AutoShortsCTA } from "@/features/shorts-auto";
import {
  InlineWizardContainer,
  type InlineWizardStep,
} from "@/features/shorts-auto-product-wizard/components/InlineWizardContainer";
import { useOrgSettings } from "@/lib/orgSettings";
import { useSceneGroups } from "@/features/videos/hooks/useSceneGroups";
import { getDetailThumbnailClass, getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";
import { Pagination } from "@/components/ui/Pagination";
import { useTopHeaderBack } from "@/components/layout/TopHeaderActionsContext";

type ViewMode = "overview" | "scenes" | "people" | "auto-shorts";

const VALID_VIEW_MODES: ViewMode[] = [
  "overview",
  "scenes",
  "people",
  "auto-shorts",
];

const SCENES_PER_PAGE = 10;

function formatHms(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function middleTruncate(filename: string, max: number): string {
  if (filename.length <= max) return filename;
  const lastDot = filename.lastIndexOf(".");
  const hasExt = lastDot > 0 && lastDot < filename.length - 1;
  const ext = hasExt ? filename.slice(lastDot) : "";
  const base = hasExt ? filename.slice(0, lastDot) : filename;
  const ellipsis = "...";
  const budget = max - ext.length - ellipsis.length;
  if (budget <= 0) {
    const head = Math.max(0, max - ellipsis.length);
    return filename.slice(0, head) + ellipsis;
  }
  const front = Math.ceil(budget / 2);
  const back = budget - front;
  return base.slice(0, front) + ellipsis + base.slice(base.length - back) + ext;
}

function formatDatetime(iso: string): string {
  const d = new Date(iso);
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${y}-${mo}-${day} ${hh}:${mm}:${ss}`;
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function ChevronUpIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
    </svg>
  );
}

function ClipboardIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  );
}

function CcIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
    </svg>
  );
}

function PlayIcon() {
  // figma: 1602:38481 lucide/play (20×20, fill currentColor, rounded line joins)
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round">
      <polygon points="6 3 21 12 6 21 6 3" />
    </svg>
  );
}

function PauseIcon() {
  // figma: 1602:38481 lucide/pause (20×20)
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round">
      <rect x="14" y="4" width="4" height="16" rx="1" />
      <rect x="6" y="4" width="4" height="16" rx="1" />
    </svg>
  );
}

function CheckCircleIcon({ filled }: { filled: boolean }) {
  if (filled) {
    return (
      <svg className="h-6 w-6 text-indigo-500" viewBox="0 0 24 24" fill="currentColor">
        <path fillRule="evenodd" d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12zm13.36-1.814a.75.75 0 10-1.22-.872l-3.236 4.53L9.53 12.22a.75.75 0 00-1.06 1.06l2.25 2.25a.75.75 0 001.14-.094l3.75-5.25z" clipRule="evenodd" />
      </svg>
    );
  }
  return (
    <svg className="h-6 w-6 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  );
}

function getParentFolderName(path: string | null | undefined): string | null {
  if (!path) return null;
  const parts = path.split("/").filter(Boolean);
  if (parts.length <= 1) return null;
  return parts[parts.length - 2].trim();
}

function VideoInfoPanel({
  videoId,
  meta,
  scenes,
  seekMs,
  seekKey,
}: {
  videoId: string;
  meta: VideoScenesResponse | null;
  scenes: VideoScene[];
  seekMs?: number | null;
  seekKey?: number;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const title = meta?.video_title || videoId;
  const lastEnd = scenes.length > 0 ? scenes[scenes.length - 1].end_ms : 0;
  const firstStart = scenes.length > 0 ? scenes[0].start_ms : 0;
  const durationMs = lastEnd - firstStart;

  // figma 1602:38481 — overlay controls: progress bar + play + skip pill + time pill
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);
  const [totalTimeMs, setTotalTimeMs] = useState(0);

  const sourceLabel =
    meta?.source_type === "gdrive" ? "Google Drive"
    : meta?.source_type === "removable_disk" ? "외장 디스크"
    : meta?.source_type === "local" ? "로컬 파일"
    : "-";

  const folderName =
    meta?.source_type === "gdrive"
      ? (getParentFolderName(meta?.source_path) || meta?.library_name || "-")
      : (meta?.library_name || meta?.source_path || "-");
  const captureDate = meta?.capture_time
    ? formatDatetime(meta.capture_time)
    : meta?.earliest_ingest_time
      ? formatDatetime(meta.earliest_ingest_time)
      : "-";

  const rows: [string, string][] = [
    ["파일 위치", sourceLabel],
    ["폴더 제목", folderName],
    ["재생 시간", durationMs > 0 ? formatHms(durationMs) : "-"],
    ["업로드 일자", captureDate],
  ];

  useEffect(() => {
    const video = videoRef.current;
    if (!video || seekMs == null) return;

    const doSeek = () => {
      video.currentTime = seekMs / 1000;
      video.play().catch(() => {});
    };

    if (video.readyState >= 1) {
      doSeek();
    } else {
      video.addEventListener("loadedmetadata", doSeek, { once: true });
      return () => video.removeEventListener("loadedmetadata", doSeek);
    }
  }, [seekMs, seekKey]);

  // 커스텀 컨트롤용 video 이벤트 바인딩
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onTime = () => setCurrentTimeMs(video.currentTime * 1000);
    const onLoaded = () => setTotalTimeMs((video.duration || 0) * 1000);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    video.addEventListener("timeupdate", onTime);
    video.addEventListener("loadedmetadata", onLoaded);
    return () => {
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("loadedmetadata", onLoaded);
    };
  }, []);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play().catch(() => {});
    } else {
      video.pause();
    }
  }, []);

  const skipBy = useCallback((deltaSec: number) => {
    const video = videoRef.current;
    if (!video || !Number.isFinite(video.duration)) return;
    const next = Math.min(video.duration, Math.max(0, video.currentTime + deltaSec));
    video.currentTime = next;
  }, []);

  const handleProgressSeek = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const video = videoRef.current;
    if (!video || !video.duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    video.currentTime = ratio * video.duration;
  }, []);

  const isCloud = meta?.source_type === "gdrive";
  const playbackUrl = isCloud
    ? getCloudPlaybackUrl(videoId)
    : getAgentPlaybackUrl(videoId);
  const posterUrl = isCloud
    ? (scenes.length > 0 ? getCloudThumbnailUrl(videoId, scenes[0].scene_id) : undefined)
    : getAgentThumbnailUrl(videoId);

  const progressRatio = totalTimeMs > 0 ? (currentTimeMs / totalTimeMs) * 100 : 0;

  const displayTotalMs = totalTimeMs > 0 ? totalTimeMs : durationMs;

  return (
    // figma: 1602:38477 — 좌측 영상 카드 (rounded-10 shadow-card, no border)
    <div className="flex flex-col overflow-hidden rounded-card bg-white shadow-card">
      {/* figma 1602:38478 — 제목 영역 flex-col items-start gap-6, pt-20 pb-10 px-20 */}
      <div className="flex min-w-0 flex-col items-start gap-1.5 px-5 pb-2.5 pt-5">
        <div className="flex min-w-0 items-center gap-2">
          <h2
            className="min-w-0 text-lg font-semibold tracking-[-0.45px] text-neutral-h-black"
            title={title}
          >
            {middleTruncate(title, 30)}
          </h2>
          <OpenInDriveButton
            sourceType={meta?.source_type ?? "local"}
            webViewLink={meta?.web_view_link}
          />
        </div>
      </div>

      {/* figma 1602:38480 — 비디오 frame 341×606 with overlay 컨트롤 */}
      <div className="relative h-[606px] w-full overflow-hidden bg-black">
        <video
          ref={videoRef}
          src={playbackUrl}
          className="absolute inset-0 h-full w-full object-contain"
          poster={posterUrl}
        />

        {/* figma 1602:38481 — 컨트롤 overlay (absolute inset-0, justify-end, p-10, gap-12) */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-start justify-end gap-3 p-2.5">
          {/* figma 1602:38482 — 진행바 (h-4 white track, navy fill) */}
          <div
            role="slider"
            tabIndex={0}
            aria-valuemin={0}
            aria-valuemax={Math.max(0, Math.round(displayTotalMs / 1000))}
            aria-valuenow={Math.round(currentTimeMs / 1000)}
            aria-label="재생 진행"
            onClick={handleProgressSeek}
            className="pointer-events-auto relative h-1 w-full cursor-pointer overflow-hidden bg-white"
          >
            <div
              className="absolute left-0 top-0 h-full bg-heimdex-navy-500"
              style={{ width: `${progressRatio}%` }}
            />
          </div>

          {/* figma 1602:38485 — 버튼 row (play 32, skip pill 72×32, time pill) */}
          <div className="pointer-events-auto flex items-center gap-2.5">
            <button
              type="button"
              onClick={togglePlay}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-[rgba(38,38,38,0.5)] text-white"
              aria-label={isPlaying ? "일시정지" : "재생"}
            >
              {isPlaying ? <PauseIcon /> : <PlayIcon />}
            </button>
            <div className="flex h-8 w-[72px] items-center justify-between rounded-full bg-[rgba(38,38,38,0.5)] px-2 py-0.5">
              <button
                type="button"
                onClick={() => skipBy(-5)}
                className="text-white"
                aria-label="5초 뒤로"
              >
                <SkipBack className="h-5 w-5" strokeWidth={1.667} />
              </button>
              <button
                type="button"
                onClick={() => skipBy(5)}
                className="text-white"
                aria-label="5초 앞으로"
              >
                <SkipForward className="h-5 w-5" strokeWidth={1.667} />
              </button>
            </div>
            <div className="flex h-8 items-center rounded-full bg-[rgba(38,38,38,0.5)] px-2 py-0.5">
              <span className="text-sm font-medium tracking-[-0.35px] text-white">
                {formatHms(currentTimeMs)} / {formatHms(displayTotalMs)}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* figma 1602:38496 / 1607:64939 — 메타 정보 (p-20, left-aligned 2 col) */}
      <div className="flex flex-col items-start p-5">
        <div className="flex items-start gap-8 text-sm font-medium leading-[1.4] tracking-[-0.35px]">
          <div className="flex flex-col items-start gap-5 whitespace-nowrap text-neutral-500">
            {rows.map(([label]) => (
              <p key={label}>{label}</p>
            ))}
          </div>
          <div className="flex flex-col items-start gap-5 whitespace-nowrap text-grayscale-800">
            {rows.map(([label, value]) => (
              <p key={label}>{value}</p>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function OverviewPanel({
  scenes,
  videoId,
  getToken,
}: {
  scenes: VideoScene[];
  videoId: string;
  getToken: () => Promise<string | null>;
}) {
  const [copiedSection, setCopiedSection] = useState<string | null>(null);
  const [summaryData, setSummaryData] = useState<VideoSummaryResponse | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState(false);

  // Fetch or generate video summary on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setSummaryLoading(true);
      setSummaryError(false);
      try {
        // Try to get existing summary
        let result = await getVideoSummary(videoId, getToken);
        if (!result && !cancelled) {
          // No summary yet — generate one
          try {
            result = await generateVideoSummary(videoId, false, getToken);
          } catch {
            // Generation failed (feature disabled, no API key, etc.) — fall back
          }
        }
        if (!cancelled) setSummaryData(result);
      } catch {
        if (!cancelled) setSummaryError(true);
      } finally {
        if (!cancelled) setSummaryLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [videoId, getToken]);

  const handleSaveSummary = useCallback(async (_field: string, value: string) => {
    const result = await editVideoSummary(videoId, value, getToken);
    setSummaryData(result);
  }, [videoId, getToken]);

  const handleResetSummary = useCallback(async (_field: string) => {
    const result = await resetVideoSummary(videoId, getToken);
    setSummaryData(result);
  }, [videoId, getToken]);

  const handleRegenerate = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const result = await generateVideoSummary(videoId, true, getToken);
      setSummaryData(result);
    } catch {
      // silently fail
    } finally {
      setSummaryLoading(false);
    }
  }, [videoId, getToken]);

  const fullTranscript = useMemo(
    () => scenes
      .filter((s) => s.transcript_raw)
      .map((s) => `[${formatTimestamp(s.start_ms)}] ${s.transcript_raw}`)
      .join("\n\n"),
    [scenes],
  );

  // 행동 요약 fallback은 타임스탬프 prefix 없는 평문 사용 (figma: 1602:38538 본문 spec)
  const transcriptPlainForSummary = useMemo(
    () => scenes
      .filter((s) => s.transcript_raw)
      .map((s) => s.transcript_raw)
      .join("\n\n"),
    [scenes],
  );

  const diarizedScenes = useMemo(
    () => scenes
      .map((s) => ({ startMs: s.start_ms, turns: parseSpeakerTranscript(s.speaker_transcript) }))
      .filter((s) => s.turns.length > 0),
    [scenes],
  );
  const hasDiarization = diarizedScenes.length > 0;

  // Fallback: concatenated scene captions (old behavior) when no AI summary
  const captionFallback = useMemo(() => {
    const captions = scenes
      .map((s) => s.scene_caption?.trim())
      .filter((c): c is string => Boolean(c));
    if (captions.length === 0) return "";
    const unique = Array.from(new Set(captions));
    const joined = unique.join("\n");
    return joined.length > 500 ? joined.slice(0, 500) + "..." : joined;
  }, [scenes]);

  const summaryText = summaryData?.summary || captionFallback || transcriptPlainForSummary;
  const hasSummary = Boolean(summaryData?.summary);
  const displaySummary = summaryText.length > 500 ? summaryText.slice(0, 500) + "..." : summaryText;

  const handleCopy = useCallback(async (text: string, section: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedSection(section);
      setTimeout(() => setCopiedSection(null), 2000);
    } catch {
      /* clipboard not available */
    }
  }, []);

  return (
    // figma: 1602:38512 — 행동요약 + 스크립트 sections; the surrounding card
    // (radius/shadow/padding) is provided by VideoDetailPage's outer wrapper.
    <div className="flex flex-col gap-6">
      {/* figma: 1602:38474 (행동요약) — 제목 우측에 복사 아이콘 + AI/수정/재생성 뱃지 */}
      <section className="flex flex-col gap-5">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold tracking-[-0.45px] text-neutral-h-black">행동 요약</h3>
          <button
            type="button"
            onClick={() => handleCopy(summaryText, "summary")}
            className="inline-flex items-center text-neutral-h-500 transition-colors hover:text-grayscale-800"
            aria-label="행동 요약 복사"
            title={copiedSection === "summary" ? "복사됨" : "복사"}
          >
            <CopyIcon className="h-4 w-4 text-neutral-h-500" />
          </button>
          {summaryLoading && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 animate-pulse">
              생성 중...
            </span>
          )}
          {!summaryLoading && hasSummary && !summaryData?.is_edited && (
            <span className="rounded-full bg-grayscale-100 px-2 py-0.5 text-xs font-medium text-heimdex-navy-500">AI</span>
          )}
          {!summaryLoading && summaryData?.is_edited && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-600">수정됨</span>
          )}
          {!summaryLoading && summaryData?.is_stale && (
            <button
              type="button"
              onClick={handleRegenerate}
              className="rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-600 hover:bg-orange-100 transition-colors"
            >
              재생성
            </button>
          )}
        </div>
        {hasSummary ? (
          <InlineEditField
            value={summaryData?.summary ?? ""}
            fieldName="video_summary"
            isEdited={summaryData?.is_edited}
            onSave={handleSaveSummary}
            onReset={summaryData?.is_edited ? handleResetSummary : undefined}
            multiline
            maxLength={5000}
            placeholder="요약 정보가 없습니다."
          />
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-[1.6] text-grayscale-600">
            {displaySummary || "요약 정보가 없습니다."}
          </p>
        )}
      </section>

      {/* figma: 1602:38542 (스크립트) — 제목 우측에 복사 아이콘, 본문만 독립 스크롤 */}
      <section className="flex flex-col gap-5">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold tracking-[-0.45px] text-neutral-h-black">스크립트</h3>
          <button
            type="button"
            onClick={() => handleCopy(fullTranscript, "script")}
            className="inline-flex items-center text-neutral-h-500 transition-colors hover:text-grayscale-800"
            aria-label="스크립트 복사"
            title={copiedSection === "script" ? "복사됨" : "복사"}
          >
            <CopyIcon className="h-4 w-4 text-neutral-h-500" />
          </button>
        </div>
        {hasDiarization ? (
          <div className="max-h-[800px] overflow-y-auto space-y-3">
            {diarizedScenes.map((ds, si) => (
              <div key={si}>
                <div className="space-y-1">
                  {ds.turns.map((turn, ti) => (
                    <div key={ti} className={cn("flex gap-2 text-sm leading-relaxed", turn.color.border, "border-l-2 pl-2")}>
                      <span className={cn("inline-flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-medium mt-0.5", turn.color.bg, turn.color.text)}>
                        {turn.label}
                      </span>
                      {turn.timestamp && (
                        <span className="text-gray-400 font-mono text-xs flex-shrink-0 mt-0.5">{turn.timestamp}</span>
                      )}
                      <span className="text-gray-700">{turn.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="max-h-[800px] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
            {fullTranscript || "스크립트가 없습니다."}
          </div>
        )}
      </section>
    </div>
  );
}

export function SceneCard({
  scene,
  index,
  videoId,
  agentAvailable,
  isSelected,
  onToggle,
  onSeek,
  isPlaying,
  aspectRatio,
  onSaveOverride,
  onResetOverride,
}: {
  scene: VideoScene;
  index: number;
  videoId: string;
  agentAvailable: boolean;
  isSelected: boolean;
  onToggle: (id: string) => void;
  onSeek?: (startMs: number) => void;
  isPlaying?: boolean;
  aspectRatio: ThumbnailAspectRatio;
  onSaveOverride?: (sceneId: string, fieldName: string, value: string | string[]) => Promise<void>;
  onResetOverride?: (sceneId: string, fieldName: string) => Promise<void>;
}) {
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [subtitleExpanded, setSubtitleExpanded] = useState(false);
  const [speakerExpanded, setSpeakerExpanded] = useState(false);

  useEffect(() => {
    if (isSelected) {
      setSummaryExpanded(true);
      setSubtitleExpanded(true);
      setSpeakerExpanded(true);
    }
  }, [isSelected]);

  const durationSec = Math.round((scene.end_ms - scene.start_ms) / 1000);
  const timeRange = `${formatVideoTimestampHMS(scene.start_ms)} - ${formatVideoTimestampHMS(scene.end_ms)}`;
  const transcriptPreview = scene.transcript_raw.length > 100
    ? scene.transcript_raw.slice(0, 100) + "..."
    : scene.transcript_raw;
  const speakerTurns = useMemo(() => parseSpeakerTranscript(scene.speaker_transcript), [scene.speaker_transcript]);
  const hasSpeakers = speakerTurns.length > 0;
  const captionText = scene.scene_caption?.trim() || "";
  const captionPreview = captionText.length > 100
    ? captionText.slice(0, 100) + "..."
    : captionText;

  void aspectRatio;
  void summaryExpanded;
  void setSummaryExpanded;
  void subtitleExpanded;
  void setSubtitleExpanded;
  void speakerExpanded;
  void setSpeakerExpanded;
  void transcriptPreview;
  void captionPreview;

  // Both portrait and landscape orientations now share the same
  // LandscapeSceneCard layout so the time chip, checkbox, and inline editors
  // stay consistent across aspect-ratio settings.
  return (
    <LandscapeSceneCard
      scene={scene}
      index={index}
      videoId={videoId}
      agentAvailable={agentAvailable}
      isSelected={isSelected}
      onToggle={onToggle}
      onSeek={onSeek}
      isPlaying={isPlaying}
      timeRange={timeRange}
      durationSec={durationSec}
      captionText={captionText}
      speakerTurns={speakerTurns}
      hasSpeakers={hasSpeakers}
      onSaveOverride={onSaveOverride}
      onResetOverride={onResetOverride}
    />
  );
}


// figma: 1602:39052 (장면 분석 카드, 16:9 가로형)
function LandscapeSceneCard({
  scene,
  index,
  videoId,
  agentAvailable,
  isSelected,
  onToggle,
  onSeek,
  isPlaying,
  timeRange,
  durationSec,
  captionText,
  speakerTurns,
  hasSpeakers,
  onSaveOverride,
  onResetOverride,
}: {
  scene: VideoScene;
  index: number;
  videoId: string;
  agentAvailable: boolean;
  isSelected: boolean;
  onToggle: (id: string) => void;
  onSeek?: (startMs: number) => void;
  isPlaying?: boolean;
  timeRange: string;
  durationSec: number;
  captionText: string;
  speakerTurns: ReturnType<typeof parseSpeakerTranscript>;
  hasSpeakers: boolean;
  onSaveOverride?: (sceneId: string, fieldName: string, value: string | string[]) => Promise<void>;
  onResetOverride?: (sceneId: string, fieldName: string) => Promise<void>;
}) {
  const bodyText = captionText || scene.transcript_raw;
  const bodyField = captionText ? "scene_caption" : "transcript_raw";

  return (
    <div
      className={cn(
        "overflow-hidden rounded-card bg-white transition-all",
        isPlaying || isSelected
          ? "border-2 border-heimdex-navy-500"
          : "border border-grayscale-100",
      )}
    >
      <div className="flex items-stretch">
        <button
          type="button"
          onClick={() => onSeek?.(scene.start_ms)}
          className="group relative w-[180px] flex-shrink-0 self-stretch overflow-hidden bg-black"
          title={`장면${index + 1} 재생`}
        >
          <SceneThumbnail
            videoId={videoId}
            sceneId={scene.scene_id}
            agentAvailable={agentAvailable}
            className="h-full w-full object-cover"
          />
          <div className="absolute inset-0 flex items-center justify-center bg-black/0 transition-colors group-hover:bg-black/30">
            <svg
              className="h-10 w-10 text-white opacity-0 drop-shadow-lg transition-opacity group-hover:opacity-100"
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M8 5v14l11-7z" />
            </svg>
          </div>
        </button>

        <div className="flex min-w-0 flex-1 flex-col gap-4 p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-grayscale-800">장면{index + 1}</span>
            <div className="flex items-center gap-2.5">
              <span className="inline-flex h-5 items-center rounded bg-grayscale-100 px-1 text-[10px] font-medium text-grayscale-500">
                {timeRange}
              </span>
              <span className="text-[10px] font-medium text-grayscale-500">{durationSec}초</span>
              <button
                type="button"
                onClick={() => onToggle(scene.scene_id)}
                aria-label={isSelected ? "선택 해제" : "선택"}
                aria-pressed={isSelected}
                className={cn(
                  "inline-flex h-[22px] w-[22px] items-center justify-center rounded-checkbox border transition-colors",
                  isSelected
                    ? "border-heimdex-navy-500 bg-heimdex-navy-500 text-white"
                    : "border-grayscale-300 bg-white text-transparent hover:border-heimdex-navy-500",
                )}
              >
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            {onSaveOverride ? (
              <InlineEditField
                value={bodyText}
                fieldName={bodyField}
                isEdited={scene.edited_fields?.includes(bodyField)}
                onSave={async (field, val) => {
                  await onSaveOverride(scene.scene_id, field, val);
                }}
                onReset={
                  onResetOverride
                    ? async (field) => {
                        await onResetOverride(scene.scene_id, field);
                      }
                    : undefined
                }
              />
            ) : (
              <p className="text-[10px] leading-[1.6] tracking-[-0.25px] text-grayscale-800">
                {bodyText}
              </p>
            )}

            <hr className="border-0 border-t border-grayscale-100" />

            <div className="flex flex-col gap-2">
              {hasSpeakers ? (
                speakerTurns.map((turn, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <div className="flex flex-shrink-0 items-center gap-1">
                      <span
                        className={cn(
                          "inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-medium",
                          turn.color.bg,
                          turn.color.text,
                        )}
                      >
                        {turn.label}
                      </span>
                      {turn.timestamp && (
                        <span className="text-[10px] font-medium text-grayscale-500">{turn.timestamp}</span>
                      )}
                    </div>
                    <p className="flex-1 text-[10px] leading-[1.6] tracking-[-0.25px] text-grayscale-800">
                      {turn.text}
                    </p>
                  </div>
                ))
              ) : (
                <p className="text-[10px] leading-[1.6] tracking-[-0.25px] text-grayscale-800">
                  <span className="font-mono text-grayscale-400">[{formatTimestamp(scene.start_ms)}]</span>{" "}
                  {scene.transcript_raw}
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ScenesPanel({
  scenes: initialScenes,
  totalScenes: initialTotal,
  videoId,
  agentAvailable,
  onSeekToScene,
  onBlurClick,
  activeSceneMs,
  getToken,
  aspectRatio,
}: {
  scenes: VideoScene[];
  totalScenes: number;
  videoId: string;
  agentAvailable: boolean;
  onSeekToScene?: (startMs: number) => void;
  onBlurClick: () => void;
  activeSceneMs?: number | null;
  getToken: () => Promise<string | null>;
  aspectRatio: ThumbnailAspectRatio;
}) {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [searchResults, setSearchResults] = useState<VideoScene[] | null>(null);
  const [searchTotal, setSearchTotal] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [currentPage, setCurrentPage] = useState(1);
  const [groupingEnabled, setGroupingEnabled] = useState(false);
  const sceneGroups = useSceneGroups(videoId, getToken);

  const [sceneOverrides, setSceneOverrides] = useState<Record<string, Partial<VideoScene>>>({});
  const displayScenes = (searchResults ?? initialScenes).map((s) => {
    const ov = sceneOverrides[s.scene_id];
    return ov ? { ...s, ...ov } : s;
  });
  const displayTotal = searchResults !== null ? searchTotal : initialTotal;

  const handleSaveOverride = useCallback(async (sceneId: string, fieldName: string, value: string | string[]) => {
    const body: Record<string, string | string[]> = { [fieldName]: value };
    await patchSceneOverride(videoId, sceneId, body, getToken);
    setSceneOverrides((prev) => ({
      ...prev,
      [sceneId]: {
        ...prev[sceneId],
        [fieldName]: value,
        is_edited: true,
        edited_fields: Array.from(new Set([...(prev[sceneId]?.edited_fields ?? []), fieldName])),
      },
    }));
  }, [videoId, getToken]);

  const handleResetOverride = useCallback(async (sceneId: string, fieldName: string) => {
    await resetSceneOverride(videoId, sceneId, fieldName, getToken);
    setSceneOverrides((prev) => {
      const existing = { ...prev[sceneId] };
      delete existing[fieldName as keyof VideoScene];
      const fields = (existing.edited_fields ?? []).filter((f) => f !== fieldName);
      return { ...prev, [sceneId]: { ...existing, edited_fields: fields, is_edited: fields.length > 0 } };
    });
  }, [videoId, getToken]);

  const totalPages = Math.max(1, Math.ceil(displayScenes.length / SCENES_PER_PAGE));
  const paginatedScenes = useMemo(() => {
    const start = (currentPage - 1) * SCENES_PER_PAGE;
    return displayScenes.slice(start, start + SCENES_PER_PAGE);
  }, [displayScenes, currentPage]);

  // Auto-paginate to the active scene's page when navigating from search
  const activeSceneRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (activeSceneMs == null || displayScenes.length === 0) return;
    const idx = displayScenes.findIndex((s) => s.start_ms === activeSceneMs);
    if (idx < 0) return;
    const targetPage = Math.floor(idx / SCENES_PER_PAGE) + 1;
    if (targetPage !== currentPage) setCurrentPage(targetPage);
  }, [activeSceneMs, displayScenes]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll the active scene card into view after pagination settles
  useEffect(() => {
    if (activeSceneRef.current) {
      activeSceneRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [currentPage, activeSceneMs]);

  const handleSearch = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim();
    setActiveSearch(q);
    setCurrentPage(1);

    if (!q) {
      setSearchResults(null);
      setSearchTotal(0);
      return;
    }

    setIsSearching(true);
    try {
      const res = await getVideoScenes(videoId, 200, 0, getToken, q);
      setSearchResults(res.scenes);
      setSearchTotal(res.total);
    } catch {
      setSearchResults([]);
      setSearchTotal(0);
    } finally {
      setIsSearching(false);
    }
  }, [searchQuery, videoId, getToken]);

  const toggleSelection = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div>
      {/* figma: 1602:39045 — border-grayscale/500 p-16 r-10, Enter to submit;
          no trailing 검색 button per the new spec. */}
      <form onSubmit={handleSearch}>
        <div className="relative">
          <SearchIcon className="absolute left-4 top-1/2 h-6 w-6 -translate-y-1/2 text-grayscale-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="영상 내에서 원하는 장면을 검색하여 찾아보세요."
            className="w-full rounded-[10px] border border-grayscale-500 bg-white p-[16px] pl-[52px] pr-10 text-[16px] font-medium leading-[1.4] tracking-[-0.4px] text-grayscale-800 placeholder:text-neutral-h-300 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
          />
          {activeSearch && (
            <button
              type="button"
              onClick={() => {
                setSearchQuery("");
                setActiveSearch("");
                setSearchResults(null);
                setSearchTotal(0);
                setCurrentPage(1);
              }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-grayscale-400 hover:text-grayscale-800"
              aria-label="검색어 지우기"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </button>
          )}
        </div>
      </form>


      <div className="mt-6 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h3 className="text-lg font-bold text-gray-900">결과</h3>
          <span className="text-sm text-gray-500">
            {groupingEnabled && sceneGroups.data && !activeSearch
              ? `${sceneGroups.data.total_groups}개 그룹 (${sceneGroups.data.total_scenes}개 장면)`
              : `${displayTotal}개 장면`}
          </span>
        </div>
        {/* figma: 1602:39047 — 결과 헤더 우측 [블러 처리][쇼츠 제작] */}
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onBlurClick}
            className="inline-flex h-8 items-center justify-center rounded-lg border border-neutral-500 bg-white px-2.5 py-1.5 text-xs font-semibold text-neutral-500 transition-colors hover:bg-grayscale-100"
          >
            블러 처리
          </button>
          <button
            type="button"
            disabled={selectedIds.size === 0}
            onClick={() => {
              if (selectedIds.size > 0) {
                router.push(`/export/shorts/editor?videoId=${videoId}&sceneIds=${Array.from(selectedIds).join(",")}`);
              }
            }}
            className={cn(
              "inline-flex h-8 items-center justify-center rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-colors",
              selectedIds.size > 0
                ? "bg-heimdex-navy-500 text-white hover:bg-heimdex-navy-600"
                : "bg-grayscale-200 text-grayscale-500 cursor-not-allowed",
            )}
          >
            쇼츠 제작
          </button>
        </div>
      </div>

      {groupingEnabled && sceneGroups.data && !activeSearch ? (
        <div className="mt-4 space-y-4">
          {sceneGroups.data.groups.map((group) => (
            <SceneGroupCard
              key={group.group_index}
              group={group}
              videoId={videoId}
              agentAvailable={agentAvailable}
              onSeekToScene={onSeekToScene}
              activeSceneMs={activeSceneMs}
              aspectRatio={aspectRatio}
            />
          ))}
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          {isSearching ? (
            <div className="flex items-center justify-center py-12">
              <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-500" />
            </div>
          ) : paginatedScenes.length === 0 ? (
            <div className="py-12 text-center text-sm text-gray-400">
              {activeSearch ? "검색 결과가 없습니다." : "장면이 없습니다."}
            </div>
          ) : (
            paginatedScenes.map((scene, i) => {
              const playing = activeSceneMs === scene.start_ms;
              return (
                <div key={scene.scene_id} ref={playing ? activeSceneRef : undefined}>
                  <SceneCard
                    scene={scene}
                    index={(currentPage - 1) * SCENES_PER_PAGE + i}
                    videoId={videoId}
                    agentAvailable={agentAvailable}
                    isSelected={selectedIds.has(scene.scene_id)}
                    onToggle={toggleSelection}
                    onSeek={onSeekToScene}
                    isPlaying={playing}
                    aspectRatio={aspectRatio}
                    onSaveOverride={handleSaveOverride}
                    onResetOverride={handleResetOverride}
                  />
                </div>
              );
            })
          )}
        </div>
      )}

      {!groupingEnabled && (
        <Pagination
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={setCurrentPage}
          className="mt-8"
        />
      )}
    </div>
  );
}

export function VideoDetailPage({ videoId }: { videoId: string }) {
  const router = useRouter();
  const { getAccessToken } = useAuth();
  const { isAvailable: agentAvailable } = useAgent();
  const searchParams = useSearchParams();
  const initialT = searchParams.get("t");
  const initialView = searchParams.get("view") as ViewMode | null;
  const [view, setViewRaw] = useState<ViewMode>(
    initialT
      ? "scenes"
      : initialView && VALID_VIEW_MODES.includes(initialView)
        ? initialView
        : "overview",
  );
  const [autoShortsStep, setAutoShortsStep] =
    useState<InlineWizardStep>("criteria");
  const [meta, setMeta] = useState<VideoScenesResponse | null>(null);
  const [scenes, setScenes] = useState<VideoScene[]>([]);
  const [totalScenes, setTotalScenes] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [seekMs, setSeekMs] = useState<number | null>(initialT ? Number(initialT) : null);
  const [seekKey, setSeekKey] = useState(initialT ? 1 : 0);
  const { settings } = useOrgSettings();
  const aspectRatio = settings.thumbnail_aspect_ratio as ThumbnailAspectRatio;

  const [reprocessStatus, setReprocessStatus] = useState<ReprocessJobResponse | null>(null);
  const [reprocessDismissed, setReprocessDismissed] = useState(false);
  const [isReprocessDialogOpen, setIsReprocessDialogOpen] = useState(false);

  // --- Blur subsystem: user-triggered only, feature-flag gated ---
  // ``router`` is declared higher up in this component; we reuse it here.
  const {
    data: blurJobs,
    disabled: blurDisabled,
    refetch: refetchBlurJobs,
  } = useBlurJobsForFile(videoId);
  const hasBlurJob = Boolean(blurJobs && blurJobs.items.length > 0);
  const [isBlurDialogOpen, setIsBlurDialogOpen] = useState(false);
  const [isBlurSubmitting, setIsBlurSubmitting] = useState(false);
  const [blurSubmitError, setBlurSubmitError] = useState<string | null>(null);

  const handleBlurClick = useCallback(() => {
    if (hasBlurJob) {
      router.push(`/videos/${videoId}/blur`);
    } else {
      setBlurSubmitError(null);
      setIsBlurDialogOpen(true);
    }
  }, [hasBlurJob, router, videoId]);

  const handleBlurSubmit = useCallback(
    async (categories: BlurCategory[]) => {
      setIsBlurSubmitting(true);
      setBlurSubmitError(null);
      try {
        await createBlurJob(
          videoId,
          { categories, do_faces: categories.includes("face") },
          getAccessToken,
        );
        setIsBlurDialogOpen(false);
        refetchBlurJobs();
        router.push(`/videos/${videoId}/blur`);
      } catch (err) {
        setBlurSubmitError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsBlurSubmitting(false);
      }
    },
    [videoId, getAccessToken, refetchBlurJobs, router],
  );

  const handleViewChange = useCallback((newView: ViewMode) => {
    setViewRaw(newView);
    // Re-entering auto-shorts always starts at the criteria step. The
    // ``InlineWizardContainer`` owns the canonical step state via local
    // useState — the page-level ``autoShortsStep`` only mirrors it for
    // layout decisions (video panel visibility). Resetting here keeps
    // the two in sync after a tab switch.
    if (newView === "auto-shorts") {
      setAutoShortsStep("criteria");
    }
    const params = new URLSearchParams(window.location.search);
    if (newView === "overview") {
      params.delete("view");
    } else {
      params.set("view", newView);
    }
    const search = params.toString();
    router.replace(`${window.location.pathname}${search ? `?${search}` : ""}`, { scroll: false });
  }, [router]);

  const handleSeekToScene = useCallback((startMs: number) => {
    setSeekMs(startMs);
    setSeekKey((k) => k + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);

    Promise.all([
      getVideoScenes(videoId, 200, 0, getAccessToken),
      getReprocessStatus(videoId, getAccessToken),
    ])
      .then(([scenesRes, statusRes]) => {
        if (cancelled) return;
        setMeta(scenesRes);
        setScenes(scenesRes.scenes);
        setTotalScenes(scenesRes.total);
        setReprocessStatus(statusRes);
        if (statusRes && (statusRes.status === "completed" || statusRes.status === "failed")) {
          const dismissKey = `heimdex_reprocess_dismissed_${videoId}`;
          if (localStorage.getItem(dismissKey) === statusRes.status) {
            setReprocessDismissed(true);
          }
        }
      })
      .catch(() => {
        if (cancelled) return;
        setMeta(null);
        setScenes([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => { cancelled = true; };
  }, [videoId, getAccessToken]);

  useEffect(() => {
    if (!reprocessStatus || (reprocessStatus.status !== "pending" && reprocessStatus.status !== "processing")) {
      return;
    }

    const interval = setInterval(async () => {
      try {
        const res = await getReprocessStatus(videoId, getAccessToken);
        setReprocessStatus(res);
        if (res?.status === "completed") {
          const scenesRes = await getVideoScenes(videoId, 200, 0, getAccessToken);
          setMeta(scenesRes);
          setScenes(scenesRes.scenes);
          setTotalScenes(scenesRes.total);
        }
      } catch (err) {
        console.error("Failed to poll reprocess status", err);
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [videoId, getAccessToken, reprocessStatus?.status]);

  const handleReprocessSubmit = async (params: ReprocessParams) => {
    try {
      const res = await reprocessScenes(videoId, params, getAccessToken);
      setReprocessStatus(res);
    } catch (err) {
      if (err instanceof Error && "status" in err && (err as { status: number }).status === 409) {
        alert("이미 진행 중인 재분석 작업이 있습니다");
      } else {
        alert("재분석 요청에 실패했습니다");
      }
      throw err;
    }
  };

  const videoTitle = meta?.video_title || videoId;

  const backSlot = useMemo(
    () => ({ label: "동영상 검색", onClick: () => router.back() }),
    [router],
  );
  useTopHeaderBack(backSlot);

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  const isReprocessing = reprocessStatus?.status === "pending" || reprocessStatus?.status === "processing";

  // Derived for the inline auto-shorts wizard. Same scene-derived
  // calculation that VideoInfoPanel uses internally — kept in sync
  // by reading from the same ``scenes`` array.
  const lastEnd = scenes.length > 0 ? scenes[scenes.length - 1].end_ms : 0;
  const firstStart = scenes.length > 0 ? scenes[0].start_ms : 0;
  const pageDurationMs = Math.max(0, lastEnd - firstStart);

  // Scene boundary set for the slider's snap behavior (D4). Union of
  // every scene's start_ms + end_ms, deduped + sorted. Memoized
  // implicitly by the scenes-list identity from useEffect — only
  // recomputes when the scenes array reference changes.
  const sceneBoundariesMs = (() => {
    if (scenes.length === 0) return [] as number[];
    const set = new Set<number>();
    for (const s of scenes) {
      set.add(s.start_ms);
      set.add(s.end_ms);
    }
    return Array.from(set).sort((a, b) => a - b);
  })();

  // Per Decision #5: the left video panel hides on the product-select
  // step of the inline wizard. Anywhere else, it stays mounted.
  const showVideoPanel = !(
    view === "auto-shorts" && autoShortsStep === "select-product"
  );

  return (
    <div className="mx-auto max-w-6xl pt-4">
      {reprocessStatus && !reprocessDismissed && (
        <div className={cn(
          "mb-6 rounded-lg p-4 text-sm font-medium flex items-center justify-between",
          isReprocessing && "bg-yellow-50 text-yellow-800",
          reprocessStatus.status === "completed" && "bg-green-50 text-green-800",
          reprocessStatus.status === "failed" && "bg-red-50 text-red-800",
        )}>
          <span>
            {isReprocessing && "장면 재분석 진행 중..."}
            {reprocessStatus.status === "completed" && `장면 재분석이 완료되었습니다. (${reprocessStatus.scene_count}개 장면)`}
            {reprocessStatus.status === "failed" && `장면 재분석에 실패했습니다: ${reprocessStatus.error}`}
          </span>
          {!isReprocessing && (
            <button
              type="button"
              onClick={() => {
                const dismissKey = `heimdex_reprocess_dismissed_${videoId}`;
                localStorage.setItem(dismissKey, reprocessStatus.status);
                setReprocessDismissed(true);
              }}
              className="ml-4 flex-shrink-0 rounded p-1 transition-colors hover:bg-black/10"
              title="닫기"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      )}

      {/* In auto-shorts view both columns share one row height per figma
          1602:36766 — items-stretch keeps the option panel matching the
          video card height. Other views keep the sticky video card so it
          stays in view while scrolling long overview/scenes lists. */}
      <div
        className={cn(
          "flex gap-[20px]",
          view === "auto-shorts" ? "items-stretch" : "items-start",
        )}
      >
        {showVideoPanel && (
          <div
            className={cn(
              "w-[341px] flex-shrink-0",
              view === "auto-shorts" ? "self-stretch" : "sticky top-4 self-start",
            )}
            data-testid="video-info-panel-slot"
          >
            <VideoInfoPanel
              videoId={videoId}
              meta={meta}
              scenes={scenes}
              seekMs={seekMs}
              seekKey={seekKey}
            />
          </div>
        )}

        {/* figma: 1602:38985 — right card holds the view tabs and the
            active panel (overview / scenes / people / auto-shorts).
            In auto-shorts view we hide the nav (tabs + action row) per
            figma 1602:36766 so the wizard takes the full card height,
            visually matching the left VideoInfoPanel.

            Card length is locked to 653×841 across every tab (figma 통일
            요청, 2026-05-18) so switching between 개요 / 장면 분석 / 인물 관리
            never reflows the surrounding layout; the active panel scrolls
            internally if its content exceeds the available height. */}
        <div className="flex h-[841px] w-[653px] flex-shrink-0 flex-col rounded-dialog bg-white p-[20px] shadow-card">
          {view !== "auto-shorts" && (
            <nav className="mb-6 flex items-center border-b border-grayscale-100">
              {([
                { key: "overview" as const, label: "개요", badge: undefined as number | undefined },
                { key: "scenes" as const, label: "장면 분석", badge: undefined as number | undefined },
                { key: "people" as const, label: "인물 관리", badge: undefined as number | undefined },
              ]).map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => handleViewChange(tab.key)}
                  className={cn(
                    "relative -mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
                    view === tab.key
                      ? "border-heimdex-navy-500 text-heimdex-navy-500"
                      : "border-transparent text-grayscale-500 hover:border-grayscale-200 hover:text-grayscale-800",
                  )}
                >
                  {tab.label}
                  {tab.badge != null && (
                    <span className="ml-1.5 inline-flex items-center rounded-full bg-grayscale-100 px-2 py-0.5 text-xs font-medium text-grayscale-500">
                      {tab.badge}
                    </span>
                  )}
                </button>
              ))}
              <div className="mb-1 ml-auto flex items-center gap-2.5">
                {!isReprocessing && (
                  <button
                    type="button"
                    onClick={() => setIsReprocessDialogOpen(true)}
                    className="inline-flex h-8 items-center justify-center rounded-lg border border-neutral-500 bg-white px-2.5 py-1.5 text-xs font-semibold text-neutral-500 transition-colors hover:bg-grayscale-10"
                  >
                    장면 재분석
                  </button>
                )}
                <AutoShortsCTA
                  videoId={videoId}
                  onClick={() => handleViewChange("auto-shorts")}
                  renderWhileProbing
                />
                <button
                  type="button"
                  onClick={() => router.push(`/export/shorts/editor?videoId=${videoId}`)}
                  className="inline-flex h-8 items-center justify-center rounded-lg border border-neutral-500 bg-white px-2.5 py-1.5 text-xs font-semibold text-neutral-500 transition-colors hover:bg-grayscale-10"
                >
                  내보내기
                </button>
              </div>
            </nav>
          )}

          {/* Active panel scroll surface — fixed-height card keeps the
              outer layout stable; long lists scroll inside the card so
              the surrounding columns never reflow. */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            {view === "overview" ? (
              <OverviewPanel
                scenes={scenes}
                videoId={videoId}
                getToken={getAccessToken}
              />
            ) : view === "scenes" ? (
              <ScenesPanel
                scenes={scenes}
                totalScenes={totalScenes}
                videoId={videoId}
                agentAvailable={agentAvailable}
                onSeekToScene={handleSeekToScene}
                onBlurClick={handleBlurClick}
                activeSceneMs={seekMs}
                getToken={getAccessToken}
                aspectRatio={aspectRatio}
              />
            ) : view === "people" ? (
              <VideoPeoplePanel
                videoId={videoId}
                scenes={scenes}
                onSeekToScene={handleSeekToScene}
                agentAvailable={agentAvailable}
                aspectRatio={aspectRatio}
              />
            ) : (
              <InlineWizardContainer
                videoId={videoId}
                videoDurationMs={pageDurationMs}
                snapTargetsMs={sceneBoundariesMs}
                onStepChange={setAutoShortsStep}
              />
            )}
          </div>
        </div>
      </div>

      <ReprocessDialog
        isOpen={isReprocessDialogOpen}
        onClose={() => setIsReprocessDialogOpen(false)}
        onSubmit={handleReprocessSubmit}
      />

      <BlurRunDialog
        isOpen={isBlurDialogOpen}
        onClose={() => setIsBlurDialogOpen(false)}
        onSubmit={handleBlurSubmit}
        submitting={isBlurSubmitting}
        submitError={blurSubmitError}
      />
    </div>
  );
}
