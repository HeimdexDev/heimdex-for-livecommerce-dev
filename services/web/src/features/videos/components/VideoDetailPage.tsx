"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useAgent } from "@/features/search/hooks/useAgent";
import { getVideoScenes, getReprocessStatus, reprocessScenes } from "@/lib/api/videos";
import { getAgentPlaybackUrl, getAgentThumbnailUrl, getCloudPlaybackUrl, getCloudThumbnailUrl } from "@/lib/agent";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { formatTimestamp } from "@/lib/api/utils";
import type { VideoScene, VideoScenesResponse, ReprocessJobResponse, ReprocessParams } from "@/lib/types";
import { cn } from "@/lib/utils";
import { OpenInDriveButton } from "@/components/OpenInDriveButton";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";
import { ReprocessDialog } from "./ReprocessDialog";
import { SceneGroupCard } from "./SceneGroupCard";
import { VideoPeoplePanel } from "./VideoPeoplePanel";
import { useOrgSettings } from "@/lib/orgSettings";
import { useSceneGroups } from "@/features/videos/hooks/useSceneGroups";
import { getDetailThumbnailClass, getThumbnailAspectClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

type ViewMode = "overview" | "scenes" | "people";

const SCENES_PER_PAGE = 10;

function formatHms(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
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

function BackArrowIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
    </svg>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function ScissorsIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M7.848 8.25l1.536.887M7.848 8.25a3 3 0 11-5.196-3 3 3 0 015.196 3zm1.536.887a2.165 2.165 0 011.083 1.839c.005.351.054.695.14 1.024M9.384 9.137l2.077 1.199M7.848 15.75l1.536-.887m-1.536.887a3 3 0 11-5.196 3 3 3 0 015.196-3zm1.536-.887a2.165 2.165 0 001.083-1.838c.005-.352.054-.695.14-1.025m-1.223 2.863l2.077-1.199m0-3.328a4.323 4.323 0 012.068-1.379l5.325-1.628a4.5 4.5 0 012.48-.044l.803.215-7.794 4.5m-2.882-1.664A4.331 4.331 0 0010.607 12m3.736 0l7.794 4.5-.803.215a4.5 4.5 0 01-2.48-.043l-5.326-1.629a4.324 4.324 0 01-2.068-1.379M14.343 12l-2.882 1.664" />
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
  onReprocessClick,
  isReprocessing,
}: {
  videoId: string;
  meta: VideoScenesResponse | null;
  scenes: VideoScene[];
  seekMs?: number | null;
  seekKey?: number;
  onReprocessClick: () => void;
  isReprocessing: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const { settings } = useOrgSettings();
  const aspectRatio = settings.thumbnail_aspect_ratio as ThumbnailAspectRatio;
  const title = meta?.video_title || videoId;
  const lastEnd = scenes.length > 0 ? scenes[scenes.length - 1].end_ms : 0;
  const firstStart = scenes.length > 0 ? scenes[0].start_ms : 0;
  const durationMs = lastEnd - firstStart;

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
    ["촬영 장소", "-"],
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

  const isCloud = meta?.source_type === "gdrive";
  const playbackUrl = isCloud
    ? getCloudPlaybackUrl(videoId)
    : getAgentPlaybackUrl(videoId);
  const posterUrl = isCloud
    ? (scenes.length > 0 ? getCloudThumbnailUrl(videoId, scenes[0].scene_id) : undefined)
    : getAgentThumbnailUrl(videoId);

  return (
    <div>
      <div className={cn(
        "w-full overflow-hidden rounded-lg bg-black",
        getThumbnailAspectClass(aspectRatio),
      )}>
        <video
          ref={videoRef}
          src={playbackUrl}
          controls
          className="h-full w-full object-contain"
          poster={posterUrl}
        />
      </div>

      <div className="mt-6 flex items-center gap-2">
        <h2 className="text-xl font-bold text-gray-900">{title}</h2>
        <OpenInDriveButton
          sourceType={meta?.source_type ?? "local"}
          webViewLink={meta?.web_view_link}
        />
        {!isReprocessing && (
          <button
            type="button"
            onClick={onReprocessClick}
            className="ml-auto rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            장면 재분석
          </button>
        )}
      </div>

      <dl className="mt-4 space-y-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline gap-4 text-sm">
            <dt className="w-[140px] flex-shrink-0 text-gray-500">{label}</dt>
            <dd className="text-gray-900">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function OverviewPanel({
  scenes,
  allTags,
}: {
  scenes: VideoScene[];
  allTags: string[];
}) {
  const [copiedSection, setCopiedSection] = useState<string | null>(null);

  const fullTranscript = useMemo(
    () => scenes
      .filter((s) => s.transcript_raw)
      .map((s) => `[${formatTimestamp(s.start_ms)}] ${s.transcript_raw}`)
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

  const captionSummary = useMemo(() => {
    const captions = scenes
      .map((s) => s.scene_caption?.trim())
      .filter((c): c is string => Boolean(c));
    if (captions.length === 0) return "";
    const unique = Array.from(new Set(captions));
    return unique.join("\n");
  }, [scenes]);

  const hasCaptions = captionSummary.length > 0;
  const summaryText = hasCaptions ? captionSummary : fullTranscript;
  const summary = summaryText.length > 500 ? summaryText.slice(0, 500) + "..." : summaryText;

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
    <div>
      <div className="mt-2">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-bold text-gray-900">행동 요약</h3>
          {hasCaptions && (
            <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-600">AI</span>
          )}
          {allTags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center rounded-full border border-indigo-200 bg-indigo-50 px-3 py-0.5 text-xs font-medium text-indigo-700"
            >
              {tag}
            </span>
          ))}
        </div>
        <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
          {summary || "요약 정보가 없습니다."}
        </p>
        <button
          type="button"
          onClick={() => handleCopy(summary, "summary")}
          className="mt-3 inline-flex items-center gap-1.5 text-sm text-gray-400 transition-colors hover:text-gray-600"
        >
          <CopyIcon />
          {copiedSection === "summary" ? "복사됨" : ""}
        </button>
      </div>

      <div className="mt-8">
        <h3 className="text-lg font-bold text-gray-900">스크립트</h3>
        {hasDiarization ? (
          <div className="mt-4 max-h-[500px] overflow-y-auto space-y-3">
            {diarizedScenes.map((ds, si) => (
              <div key={si}>
                <div className="space-y-1">
                  {ds.turns.map((turn, ti) => (
                    <div key={ti} className={cn("flex gap-2 text-sm leading-relaxed", turn.color.border, "border-l-2 pl-2")}>
                      <span className={cn("inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold mt-0.5", turn.color.bg, turn.color.text)}>
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
          <div className="mt-4 max-h-[500px] overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
            {fullTranscript || "스크립트가 없습니다."}
          </div>
        )}
        <button
          type="button"
          onClick={() => handleCopy(fullTranscript, "script")}
          className="mt-3 inline-flex items-center gap-1.5 text-sm text-gray-400 transition-colors hover:text-gray-600"
        >
          <CopyIcon />
          {copiedSection === "script" ? "복사됨" : ""}
        </button>
      </div>
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
  const timeRange = `${formatTimestamp(scene.start_ms)} - ${formatTimestamp(scene.end_ms)}`;
  const transcriptPreview = scene.transcript_raw.length > 100
    ? scene.transcript_raw.slice(0, 100) + "..."
    : scene.transcript_raw;
  const speakerTurns = useMemo(() => parseSpeakerTranscript(scene.speaker_transcript), [scene.speaker_transcript]);
  const hasSpeakers = speakerTurns.length > 0;
  const captionText = scene.scene_caption?.trim() || "";
  const captionPreview = captionText.length > 100
    ? captionText.slice(0, 100) + "..."
    : captionText;

  const tags = [...scene.keyword_tags, ...scene.product_tags].slice(0, 3);
  const aiTags = (scene.ai_tags ?? []).slice(0, 4);

  return (
    <div
      className={cn(
        "rounded-xl border bg-white transition-all",
        isPlaying
          ? "border-indigo-500 border-l-4 border-l-indigo-500 ring-2 ring-indigo-500/20"
          : isSelected
            ? "border-indigo-500 ring-2 ring-indigo-500/20"
            : "border-gray-200",
      )}
    >
      <div className="flex gap-0">
        <div className={cn("flex-shrink-0", getDetailThumbnailClass(aspectRatio))}>
          <button
            type="button"
            onClick={() => onSeek?.(scene.start_ms)}
            className="relative group w-full cursor-pointer"
            title={`장면${index + 1} 재생`}
          >
            <SceneThumbnail
              videoId={videoId}
              sceneId={scene.scene_id}
              agentAvailable={agentAvailable}
              className={cn("w-full rounded-tl-xl", getThumbnailAspectClass(aspectRatio))}
            />
            <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/30 transition-colors rounded-tl-xl">
              <svg
                className="h-10 w-10 text-white opacity-0 group-hover:opacity-100 transition-opacity drop-shadow-lg"
                fill="currentColor"
                viewBox="0 0 24 24"
              >
                <path d="M8 5v14l11-7z" />
              </svg>
            </div>
          </button>
          {(tags.length > 0 || aiTags.length > 0) && (
            <div className="px-3 py-2 flex flex-wrap gap-1">
              {tags.map((tag) => (
                <span
                  key={tag}
                  className="inline-flex rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700"
                >
                  {tag}
                </span>
              ))}
              {aiTags.map((tag) => (
                <span
                  key={`ai-${tag}`}
                  className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0 p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-gray-900">장면{index + 1}</span>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{timeRange}</span>
              <span className="text-xs text-gray-500">{durationSec}초</span>
              <button type="button" onClick={() => onToggle(scene.scene_id)}>
                <CheckCircleIcon filled={isSelected} />
              </button>
            </div>
          </div>

          <div className="mt-3 border-t border-gray-100 pt-3">
            <button
              type="button"
              onClick={() => setSummaryExpanded((v) => !v)}
              className="flex w-full items-center justify-between"
            >
              <div className="flex items-center gap-2 text-sm text-gray-700">
                <ClipboardIcon />
                <span className="font-medium">행동 요약</span>
                {captionText && (
                  <span className="rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-600">AI</span>
                )}
              </div>
              {summaryExpanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
            </button>
            <p className={cn(
              "mt-2 text-sm leading-relaxed text-gray-600",
              !summaryExpanded && "line-clamp-2",
            )}>
              {captionText
                ? (summaryExpanded ? captionText : captionPreview)
                : (summaryExpanded ? scene.transcript_raw : transcriptPreview)}
            </p>
          </div>

          {hasSpeakers ? (
            <div className="mt-3 border-t border-gray-100 pt-3">
              <button
                type="button"
                onClick={() => setSpeakerExpanded((v) => !v)}
                className="flex w-full items-center justify-between"
              >
                <div className="flex items-center gap-2 text-sm text-gray-700">
                  <CcIcon />
                  <span className="font-medium">자막</span>
                  {(scene.speaker_count ?? 0) > 1 && (
                    <span className="rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-600">
                      화자 {scene.speaker_count}명
                    </span>
                  )}
                </div>
                {speakerExpanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
              </button>
              <div className={cn("mt-2 space-y-1", !speakerExpanded && "max-h-[4.5rem] overflow-hidden")}>
                {speakerTurns.map((turn, i) => (
                  <div key={i} className={cn("flex gap-2 text-sm leading-relaxed", turn.color.border, "border-l-2 pl-2")}>
                    <span className={cn("inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold mt-0.5", turn.color.bg, turn.color.text)}>
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
          ) : (
            <div className="mt-3 border-t border-gray-100 pt-3">
              <button
                type="button"
                onClick={() => setSubtitleExpanded((v) => !v)}
                className="flex w-full items-center justify-between"
              >
                <div className="flex items-center gap-2 text-sm text-gray-700">
                  <CcIcon />
                  <span className="font-medium">자막</span>
                </div>
                {subtitleExpanded ? <ChevronUpIcon /> : <ChevronDownIcon />}
              </button>
              <p className={cn(
                "mt-2 text-sm leading-relaxed text-gray-600",
                !subtitleExpanded && "line-clamp-2",
              )}>
                <span className="text-gray-400 font-mono text-xs">[{formatTimestamp(scene.start_ms)}]</span>{" "}
                {subtitleExpanded ? scene.transcript_raw : transcriptPreview}
              </p>
            </div>
          )}
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
  activeSceneMs,
  getToken,
  aspectRatio,
}: {
  scenes: VideoScene[];
  totalScenes: number;
  videoId: string;
  agentAvailable: boolean;
  onSeekToScene?: (startMs: number) => void;
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

  const displayScenes = searchResults ?? initialScenes;
  const displayTotal = searchResults !== null ? searchTotal : initialTotal;

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

  const pageNumbers = useMemo(() => {
    const result: (number | "ellipsis")[] = [];
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) result.push(i);
    } else {
      result.push(1);
      let start = Math.max(2, currentPage - 1);
      let end = Math.min(totalPages - 1, currentPage + 1);
      if (currentPage <= 3) { start = 2; end = Math.min(5, totalPages - 1); }
      else if (currentPage >= totalPages - 2) { start = Math.max(2, totalPages - 4); end = totalPages - 1; }
      if (start > 2) result.push("ellipsis");
      for (let i = start; i <= end; i++) result.push(i);
      if (end < totalPages - 1) result.push("ellipsis");
      result.push(totalPages);
    }
    return result;
  }, [currentPage, totalPages]);

  const btnBase = "inline-flex h-8 w-8 items-center justify-center rounded text-sm transition-colors";

  return (
    <div>
      <h2 className="text-lg font-bold text-gray-900">장면 검색</h2>

      <form onSubmit={handleSearch} className="mt-4 flex items-center gap-3">
        <div className="relative flex-1">
          <SearchIcon className="absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="파일 내에서 원하는 장면을 검색하여 찾아보세요."
            className="w-full rounded-lg border border-gray-200 bg-gray-50 py-3 pl-12 pr-10 text-sm placeholder:text-gray-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
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
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </button>
          )}
        </div>
        <button
          type="submit"
          className="rounded-lg bg-indigo-500 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo-600"
        >
          검색
        </button>
      </form>

      {initialTotal >= 5 && !activeSearch && (
        <div className="mt-4 flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              const next = !groupingEnabled;
              setGroupingEnabled(next);
              if (next && !sceneGroups.data) {
                sceneGroups.fetchGroups();
              }
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
              groupingEnabled
                ? "bg-indigo-100 text-indigo-700 ring-1 ring-indigo-300"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200",
            )}
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
            의미 그룹
          </button>
          {groupingEnabled && sceneGroups.isLoading && (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-600" />
          )}
          {groupingEnabled && sceneGroups.error && (
            <span className="text-xs text-red-500">{sceneGroups.error}</span>
          )}
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <h3 className="text-lg font-bold text-gray-900">결과</h3>
          <span className="text-sm text-gray-500">
            {groupingEnabled && sceneGroups.data && !activeSearch
              ? `${sceneGroups.data.total_groups}개 그룹 (${sceneGroups.data.total_scenes}개 장면)`
              : `${displayTotal}개 장면`}
          </span>
        </div>
        <button
          type="button"
          disabled={selectedIds.size === 0}
          onClick={() => {
            if (selectedIds.size > 0) {
              router.push(`/shorts/create?videoId=${videoId}&sceneIds=${Array.from(selectedIds).join(",")}`);
            }
          }}
          className={cn(
            "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            selectedIds.size > 0
              ? "bg-indigo-500 text-white hover:bg-indigo-600"
              : "bg-gray-300 text-gray-500 cursor-not-allowed",
          )}
        >
          <ScissorsIcon />
          쇼츠 제작
        </button>
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
                  />
                </div>
              );
            })
          )}
        </div>
      )}

      {totalPages > 1 && !groupingEnabled && (
        <nav className="mt-8 flex items-center justify-center gap-1">
          <button
            type="button"
            disabled={currentPage === 1}
            onClick={() => setCurrentPage(1)}
            className={cn(btnBase, currentPage === 1 ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}
          >
            &laquo;
          </button>
          <button
            type="button"
            disabled={currentPage === 1}
            onClick={() => setCurrentPage((p) => p - 1)}
            className={cn(btnBase, currentPage === 1 ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}
          >
            &lsaquo;
          </button>
          {pageNumbers.map((p, i) =>
            p === "ellipsis" ? (
              <span key={`ell-${i}`} className="inline-flex h-8 w-8 items-center justify-center text-sm text-gray-400">
                &hellip;
              </span>
            ) : (
              <button
                key={p}
                type="button"
                onClick={() => setCurrentPage(p)}
                className={cn(
                  btnBase,
                  currentPage === p ? "bg-indigo-500 font-medium text-white" : "text-gray-600 hover:bg-gray-100",
                )}
              >
                {p}
              </button>
            ),
          )}
          <button
            type="button"
            disabled={currentPage === totalPages}
            onClick={() => setCurrentPage((p) => p + 1)}
            className={cn(btnBase, currentPage === totalPages ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}
          >
            &rsaquo;
          </button>
          <button
            type="button"
            disabled={currentPage === totalPages}
            onClick={() => setCurrentPage(totalPages)}
            className={cn(btnBase, currentPage === totalPages ? "cursor-not-allowed text-gray-300" : "text-gray-500 hover:bg-gray-100")}
          >
            &raquo;
          </button>
        </nav>
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
      : initialView && (["overview", "scenes", "people"] as ViewMode[]).includes(initialView)
        ? initialView
        : "overview",
  );
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

  const handleViewChange = useCallback((newView: ViewMode) => {
    setViewRaw(newView);
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

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    for (const s of scenes) {
      for (const t of s.keyword_tags) tags.add(t);
      for (const t of s.product_tags) tags.add(t);
      for (const t of s.ai_tags ?? []) tags.add(t);
    }
    return Array.from(tags);
  }, [scenes]);

  const videoTitle = meta?.video_title || videoId;

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  const isReprocessing = reprocessStatus?.status === "pending" || reprocessStatus?.status === "processing";

  return (
    <div className="mx-auto max-w-6xl pt-4">
      <div className="mb-4 flex items-center gap-3 text-sm text-gray-500">
        <button type="button" onClick={() => router.back()} className="rounded-full p-1 hover:bg-gray-200">
          <BackArrowIcon />
        </button>
        <button type="button" onClick={() => router.back()} className="hover:text-gray-700">전체 아카이브 검색</button>
        <span>&gt;</span>
        <span className="text-gray-700">{videoTitle}</span>
      </div>

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

      <nav className="mb-6 flex items-center border-b border-gray-200">
        {([
          { key: "overview" as const, label: "개요", badge: undefined as number | undefined },
          { key: "scenes" as const, label: "장면 분석", badge: totalScenes > 0 ? totalScenes : undefined },
          { key: "people" as const, label: "인물 관리", badge: undefined as number | undefined },
        ]).map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => handleViewChange(tab.key)}
            className={cn(
              "relative px-4 py-2.5 text-sm font-medium -mb-px border-b-2 transition-colors",
              view === tab.key
                ? "border-indigo-500 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300",
            )}
          >
            {tab.label}
            {tab.badge != null && (
              <span className="ml-1.5 inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                {tab.badge}
              </span>
            )}
          </button>
        ))}
        <button
          type="button"
          onClick={() => router.push(`/shorts/create?videoId=${videoId}`)}
          className="ml-auto mb-1 inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
        >
          <DownloadIcon />
          내보내기
        </button>
      </nav>

      <div className="flex items-start gap-8">
        <div className="sticky top-4 w-[45%] flex-shrink-0 self-start">
          <VideoInfoPanel
            videoId={videoId}
            meta={meta}
            scenes={scenes}
            seekMs={seekMs}
            seekKey={seekKey}
            onReprocessClick={() => setIsReprocessDialogOpen(true)}
            isReprocessing={isReprocessing}
          />

          {view === "scenes" && allTags.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1">
              {allTags.slice(0, 3).map((tag) => (
                <span
                  key={tag}
                  className="inline-flex rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-0.5 text-xs text-indigo-700"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          {view === "overview" ? (
            <OverviewPanel
              scenes={scenes}
              allTags={allTags}
            />
          ) : view === "scenes" ? (
            <ScenesPanel
              scenes={scenes}
              totalScenes={totalScenes}
              videoId={videoId}
              agentAvailable={agentAvailable}
              onSeekToScene={handleSeekToScene}
              activeSceneMs={seekMs}
              getToken={getAccessToken}
              aspectRatio={aspectRatio}
            />
          ) : (
            <VideoPeoplePanel
              videoId={videoId}
              scenes={scenes}
              onSeekToScene={handleSeekToScene}
              agentAvailable={agentAvailable}
              aspectRatio={aspectRatio}
            />
          )}
        </div>
      </div>

      <ReprocessDialog
        isOpen={isReprocessDialogOpen}
        onClose={() => setIsReprocessDialogOpen(false)}
        onSubmit={handleReprocessSubmit}
      />
    </div>
  );
}
