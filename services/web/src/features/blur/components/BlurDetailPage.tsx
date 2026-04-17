/**
 * Dedicated blur detail page. Mounted at ``/videos/[videoId]/blur``.
 *
 * Responsibilities:
 *   1. Resolve the most recent blur job for the given video (via the
 *      list endpoint) and drive every other section off it.
 *   2. While the job is running, render a progress bar sourced from
 *      the heartbeat endpoint (``progress_pct``, ``phase``).
 *   3. When the job is done, let the user toggle between the original
 *      and blurred MP4 in a native ``<video>`` element, render a
 *      timeline of detections by category (SVG lanes) fetched from the
 *      presigned manifest URL, and expose a ProRes 4444 layer export
 *      panel with category checkboxes + live export progress +
 *      download link.
 *   4. All sub-components are co-located to keep Phase 5 reviewable as
 *      a single surface.
 *
 * This page does NOT render before the blur subsystem is ready: it
 * assumes the caller already holds a blur job id (from
 * VideoDetailPage), and 404s gracefully if the feature flag is off.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useMemo, useRef, useState, forwardRef } from "react";

import {
  BlurCategory,
  BlurExportFormat,
  BlurJobResponse,
  buildBlurExportDownloadHref,
  createBlurExport,
} from "@/lib/api/blur";
import { useBlurExport, useBlurJob, useBlurJobsForFile } from "@/features/blur/hooks/useBlurJob";
import { useAuth } from "@/lib/auth";
import { getVideoScenes } from "@/lib/api/videos";
import type { VideoScene, VideoScenesResponse } from "@/lib/types/videos";
import { TimelineRuler, PlayheadCursor, msToPixels, pixelsToMs, formatTimelineTimestamp, DEFAULT_ZOOM, MIN_ZOOM, MAX_ZOOM } from "@/lib/timeline";

// ---------- shared types sourced from the manifest JSON on S3 ----------

interface BlurManifestDetection {
  frame_idx: number;
  t_ms: number;
  category: string;
  label: string;
  confidence: number;
  bbox_norm: [number, number, number, number];
  from_cache: boolean;
}

interface BlurManifest {
  schema_version: string;
  video: { fps: number; width: number; height: number; frame_count: number };
  summary: Record<string, number>;
  detections: BlurManifestDetection[];
  mask_s3_keys: Record<string, string> | null;
}

// ---------- korean labels (co-located, no i18n lib on this repo) ----------

const CATEGORY_LABELS: Record<string, string> = {
  face: "얼굴",
  license_plate: "번호판",
  card_object: "신용카드",
  logo: "로고",
  object: "기타",
};

const PHASE_LABELS: Record<string, string> = {
  queued: "대기 중",
  initializing: "모델 준비 중",
  detecting: "검출 중",
  encoding: "인코딩 중",
  uploading: "업로드 중",
  finalizing: "마무리 중",
};

const STATUS_BADGE_CLASS: Record<string, string> = {
  queued: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-700",
};

const BLUR_CATEGORY_CONFIG: Record<string, { label: string; color: string; bgClass: string }> = {
  face: { label: "얼굴", color: "#22C55E", bgClass: "bg-green-500" },
  license_plate: { label: "번호판", color: "#22C55E", bgClass: "bg-green-500" },
  card_object: { label: "신용카드", color: "#22C55E", bgClass: "bg-green-500" },
  logo: { label: "브랜드", color: "#A855F7", bgClass: "bg-purple-500" },
  object: { label: "기타", color: "#F97316", bgClass: "bg-orange-500" },
};

const FALLBACK_CATEGORY_CONFIG = { label: "기타", color: "#6B7280", bgClass: "bg-gray-500" };

function getCategoryConfig(category: string) {
  return BLUR_CATEGORY_CONFIG[category] ?? FALLBACK_CATEGORY_CONFIG;
}

function formatTime(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ============================================================================
// useBlurManifest — fetches the presigned manifest URL JSON
// ============================================================================

function useBlurManifest(url: string | null): {
  manifest: BlurManifest | null;
  loading: boolean;
  error: Error | null;
} {
  const [manifest, setManifest] = useState<BlurManifest | null>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(url));
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!url) {
      setManifest(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`manifest fetch failed (${res.status})`);
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        setManifest(data as BlurManifest);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return { manifest, loading, error };
}

// ============================================================================
// BlurHeader
// ============================================================================

function BlurHeader({
  videoId,
  job,
}: {
  videoId: string;
  job: BlurJobResponse | null;
}) {
  const status = job?.status ?? "queued";
  const badgeClass = STATUS_BADGE_CLASS[status] ?? "bg-gray-100 text-gray-700";

  return (
    <div className="mb-4 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Link
          href={`/videos/${videoId}`}
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← 영상 상세로
        </Link>
        <h1 className="text-xl font-semibold text-gray-900">블러 처리</h1>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${badgeClass}`}>
          {status}
        </span>
      </div>
    </div>
  );
}

// ============================================================================
// BlurPlayer — swaps video src between original and blurred
// ============================================================================

const BlurPlayer = forwardRef<HTMLVideoElement, { job: BlurJobResponse }>(
  function BlurPlayer({ job }, ref) {
    const storageKey = `heimdex_blur_view_${job.id}`;
    const [blurOn, setBlurOn] = useState<boolean>(() => {
      if (typeof window === "undefined") return true;
      const stored = window.localStorage.getItem(storageKey);
      return stored == null ? true : stored === "1";
    });

    useEffect(() => {
      if (typeof window === "undefined") return;
      window.localStorage.setItem(storageKey, blurOn ? "1" : "0");
    }, [blurOn, storageKey]);

    const src = blurOn ? job.blurred_playback_url : null;
    const hasBlurred = Boolean(job.blurred_playback_url);

    return (
      <div className="rounded-xl border border-gray-200 bg-black">
        {src ? (
          <video
            ref={ref}
            key={src}
            src={src}
            playsInline
            className="h-auto w-full rounded-t-xl"
          />
        ) : (
          <div className="flex aspect-video items-center justify-center rounded-t-xl bg-gray-900 text-gray-400">
            {hasBlurred
              ? "블러 OFF 상태에서 원본 재생은 영상 상세 페이지에서 확인해주세요."
              : "블러 결과를 불러올 수 없습니다."}
          </div>
        )}
        <div className="flex items-center justify-between gap-3 rounded-b-xl bg-white p-3">
          <div className="text-sm text-gray-700">
            {blurOn ? "블러 적용 중" : "블러 해제됨"}
          </div>
          <button
            type="button"
            onClick={() => setBlurOn((v) => !v)}
            disabled={!hasBlurred}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {blurOn ? "블러 끄기" : "블러 켜기"}
          </button>
        </div>
      </div>
    );
  },
);

// ============================================================================
// BlurProgressPanel
// ============================================================================

function BlurProgressPanel({ job }: { job: BlurJobResponse }) {
  const pct = Math.max(0, Math.min(100, job.progress_pct ?? 0));
  const phaseLabel = job.phase ? PHASE_LABELS[job.phase] ?? job.phase : "처리 대기";

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div className="flex items-center justify-between text-sm font-medium text-blue-900">
        <span>{phaseLabel}</span>
        <span>{pct}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-blue-100">
        <div
          className="h-full rounded-full bg-blue-600 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-blue-700">
        모델 추론과 인코딩이 진행 중입니다. 몇 분 정도 걸릴 수 있습니다.
      </p>
    </div>
  );
}

// ============================================================================
// useBlurScenes — fetch scene list for the video
// ============================================================================

function useBlurScenes(videoId: string) {
  const { getAccessToken } = useAuth();
  const [scenes, setScenes] = useState<VideoScene[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getVideoScenes(videoId, 100, 0, getAccessToken)
      .then((res) => {
        if (!cancelled) setScenes(res.scenes);
      })
      .catch(() => {
        if (!cancelled) setScenes([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [videoId, getAccessToken]);

  return { scenes, loading };
}

// ============================================================================
// BlurSceneCard — single scene card in sidebar
// ============================================================================

function BlurSceneCard({
  scene,
  detectionCount,
  isActive,
  onClick,
}: {
  scene: VideoScene;
  detectionCount: number;
  isActive: boolean;
  onClick: () => void;
}) {
  const durationSec = Math.max(1, Math.round((scene.end_ms - scene.start_ms) / 1000));
  const transcript = scene.transcript_raw?.slice(0, 80) || scene.scene_caption?.slice(0, 80) || "";

  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        isActive
          ? "border-blue-400 bg-blue-50"
          : "border-gray-200 bg-white hover:bg-gray-50"
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-900">
            {formatTime(scene.start_ms)} – {formatTime(scene.end_ms)}
          </span>
          <span className="text-[10px] text-gray-500">{durationSec}초</span>
        </div>
        {detectionCount > 0 && (
          <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700">
            {detectionCount}
          </span>
        )}
      </div>
      {transcript && (
        <p className="mt-1.5 line-clamp-2 text-xs text-gray-600">{transcript}</p>
      )}
      {scene.speaker_transcript && (
        <p className="mt-1 line-clamp-1 text-[10px] text-gray-400">
          {scene.speaker_transcript.split("\n")[0]}
        </p>
      )}
    </button>
  );
}

// ============================================================================
// BlurCategoryFilter — pill buttons to filter timeline by category
// ============================================================================

function BlurCategoryFilter({
  categories,
  summary,
  selected,
  onSelect,
}: {
  categories: string[];
  summary: Record<string, number>;
  selected: string | null;
  onSelect: (category: string | null) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
          selected === null
            ? "border-gray-900 bg-gray-900 text-white"
            : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
        }`}
      >
        전체
      </button>
      {categories.map((cat) => {
        const config = getCategoryConfig(cat);
        const isActive = selected === cat;
        return (
          <button
            key={cat}
            type="button"
            onClick={() => onSelect(isActive ? null : cat)}
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              isActive
                ? "text-white border-transparent"
                : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
            }`}
            style={isActive ? { backgroundColor: config.color } : undefined}
          >
            {!isActive && <span className={`inline-block h-2 w-2 rounded-full ${config.bgClass}`} />}
            {config.label}
            {summary[cat] != null && (
              <span className="text-[10px] opacity-70">{summary[cat]}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ============================================================================
// BlurTransportControls — play/pause, skip, timecode
// ============================================================================

function BlurTransportControls({
  playheadMs,
  totalDurationMs,
  isPlaying,
  onTogglePlay,
  onSkipPrev,
  onSkipNext,
}: {
  playheadMs: number;
  totalDurationMs: number;
  isPlaying: boolean;
  onTogglePlay: () => void;
  onSkipPrev: () => void;
  onSkipNext: () => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={onSkipPrev} className="rounded p-1 text-gray-600 hover:bg-gray-100">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="19 20 9 12 19 4 19 20" /><line x1="5" y1="19" x2="5" y2="5" />
        </svg>
      </button>
      <button type="button" onClick={onTogglePlay} className="rounded p-1 text-gray-600 hover:bg-gray-100">
        {isPlaying ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
        )}
      </button>
      <button type="button" onClick={onSkipNext} className="rounded p-1 text-gray-600 hover:bg-gray-100">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="5 4 15 12 5 20 5 4" /><line x1="19" y1="5" x2="19" y2="19" />
        </svg>
      </button>
      <span className="ml-2 font-mono text-xs text-gray-600">
        {formatTimelineTimestamp(playheadMs)} / {formatTimelineTimestamp(totalDurationMs)}
      </span>
    </div>
  );
}

// ============================================================================
// BlurDetectionTrack — color-coded detection blocks on a horizontal track
// ============================================================================

function BlurDetectionTrack({
  detections,
  totalDurationMs,
  zoom,
  onSeek,
}: {
  detections: BlurManifestDetection[];
  totalDurationMs: number;
  zoom: number;
  onSeek: (ms: number) => void;
}) {
  const totalWidth = msToPixels(totalDurationMs + 2000, zoom);
  const laneHeight = 80;
  const laneGap = 4;

  const lanes = useMemo(() => {
    const byCategory: Record<string, BlurManifestDetection[]> = {};
    for (const d of detections) {
      (byCategory[d.category] ||= []).push(d);
    }
    return Object.entries(byCategory);
  }, [detections]);

  const trackHeight = Math.max(laneHeight, lanes.length * (laneHeight + laneGap));

  return (
    <div className="relative" style={{ width: totalWidth, height: trackHeight }}>
      {lanes.map(([category, dets], laneIdx) => {
        const config = getCategoryConfig(category);
        const y = laneIdx * (laneHeight + laneGap);
        return (
          <div key={category} className="absolute left-0" style={{ top: y, height: laneHeight, width: totalWidth }}>
            <div className="h-full w-full bg-gray-50" style={{ width: totalWidth }} />
            {dets.map((d, i) => {
              const left = msToPixels(d.t_ms, zoom);
              const blockWidth = Math.max(6, msToPixels(2000, zoom));
              return (
                <div
                  key={`${category}-${i}`}
                  className="absolute top-0 cursor-pointer rounded-sm opacity-85 hover:opacity-100 transition-opacity"
                  style={{
                    left,
                    width: blockWidth,
                    height: laneHeight,
                    backgroundColor: config.color,
                  }}
                  onClick={() => onSeek(d.t_ms)}
                  title={`${config.label} · ${formatTime(d.t_ms)} · ${(d.confidence * 100).toFixed(0)}%`}
                />
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// ============================================================================
// BlurTimelineSection — full NLE timeline with ruler, tracks, playhead
// ============================================================================

function BlurTimelineSection({
  manifest,
  playheadMs,
  isPlaying,
  onSeek,
  onTogglePlay,
}: {
  manifest: BlurManifest;
  playheadMs: number;
  isPlaying: boolean;
  onSeek: (ms: number) => void;
  onTogglePlay: () => void;
}) {
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const totalDurationMs = useMemo(() => {
    if (manifest.video.frame_count <= 0) return 1;
    return Math.round((manifest.video.frame_count * 1000) / manifest.video.fps);
  }, [manifest]);

  const categories = useMemo(() => {
    const cats = new Set<string>();
    for (const d of manifest.detections) cats.add(d.category);
    return Array.from(cats);
  }, [manifest]);

  const filteredDetections = useMemo(() => {
    if (!selectedCategory) return manifest.detections;
    return manifest.detections.filter((d) => d.category === selectedCategory);
  }, [manifest, selectedCategory]);

  const sortedDetections = useMemo(
    () => [...manifest.detections].sort((a, b) => a.t_ms - b.t_ms),
    [manifest],
  );

  const skipPrev = useCallback(() => {
    const prev = sortedDetections.filter((d) => d.t_ms < playheadMs - 500);
    if (prev.length > 0) onSeek(prev[prev.length - 1].t_ms);
  }, [sortedDetections, playheadMs, onSeek]);

  const skipNext = useCallback(() => {
    const next = sortedDetections.find((d) => d.t_ms > playheadMs + 500);
    if (next) onSeek(next.t_ms);
  }, [sortedDetections, playheadMs, onSeek]);

  const trackHeight = Math.max(80, categories.length * 84);

  if (manifest.detections.length === 0) {
    return (
      <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-500">
        검출된 영역이 없습니다.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2">
        <BlurCategoryFilter
          categories={categories}
          summary={manifest.summary}
          selected={selectedCategory}
          onSelect={setSelectedCategory}
        />
        <div className="flex items-center gap-4">
          <BlurTransportControls
            playheadMs={playheadMs}
            totalDurationMs={totalDurationMs}
            isPlaying={isPlaying}
            onTogglePlay={onTogglePlay}
            onSkipPrev={skipPrev}
            onSkipNext={skipNext}
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 25))}
              className="rounded p-1 text-gray-500 hover:bg-gray-100"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="5" y1="12" x2="19" y2="12" /></svg>
            </button>
            <input
              type="range"
              min={MIN_ZOOM}
              max={MAX_ZOOM}
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
              className="h-1 w-20 accent-gray-600"
            />
            <button
              type="button"
              onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 25))}
              className="rounded p-1 text-gray-500 hover:bg-gray-100"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            </button>
          </div>
        </div>
      </div>
      <div ref={scrollRef} className="overflow-x-auto">
        <div className="relative">
          <TimelineRuler totalDurationMs={totalDurationMs} zoom={zoom} />
          <BlurDetectionTrack
            detections={filteredDetections}
            totalDurationMs={totalDurationMs}
            zoom={zoom}
            onSeek={onSeek}
          />
          <PlayheadCursor
            playheadMs={playheadMs}
            zoom={zoom}
            height={24 + trackHeight}
            onSeek={onSeek}
          />
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// BlurCategoryStats — per-category counts
// ============================================================================

function BlurCategoryStats({ summary }: { summary: Record<string, number> }) {
  const entries = Object.entries(summary).filter(([, n]) => n > 0);
  if (entries.length === 0) {
    return null;
  }
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">카테고리별 검출 수</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {entries.map(([category, count]) => (
          <div key={category} className="rounded-lg bg-gray-50 p-3">
            <div className="text-xs text-gray-500">
              {CATEGORY_LABELS[category] ?? category}
            </div>
            <div className="mt-1 text-lg font-semibold text-gray-900">{count}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// BlurExportPanel — category checkboxes + submit + live export progress
// ============================================================================

function BlurExportPanel({
  jobId,
  availableCategories,
}: {
  jobId: string;
  availableCategories: string[];
}) {
  const { getAccessToken } = useAuth();
  const [selected, setSelected] = useState<Record<string, boolean>>(() => {
    const m: Record<string, boolean> = {};
    for (const c of availableCategories) m[c] = true;
    return m;
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [exportId, setExportId] = useState<string | null>(null);

  const exportState = useBlurExport(exportId);

  const anySelected = availableCategories.some((c) => selected[c]);

  const handleSubmit = useCallback(async () => {
    const categories = availableCategories.filter((c) => selected[c]) as BlurCategory[];
    if (categories.length === 0) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await createBlurExport(jobId, categories, "prores_4444" as BlurExportFormat, getAccessToken);
      setExportId(res.id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }, [availableCategories, jobId, selected, getAccessToken]);

  const exp = exportState.data;
  const isActive = exp && (exp.status === "queued" || exp.status === "running");
  const isDone = exp && exp.status === "done";
  const isFailed = exp && exp.status === "failed";

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-gray-900">
        NLE 레이어 내보내기 (ProRes 4444)
      </h3>
      <p className="mb-3 text-xs text-gray-500">
        선택한 카테고리만 포함된 알파 레이어 ``.mov``를 생성합니다.
        Premiere / DaVinci / FCP에서 원본 위에 올려 추가 편집하세요.
      </p>

      <div className="space-y-2">
        {availableCategories.map((category) => (
          <label key={category} className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-gray-300 text-blue-600"
              checked={selected[category] ?? false}
              onChange={() => setSelected((prev) => ({ ...prev, [category]: !prev[category] }))}
              disabled={submitting || Boolean(isActive)}
            />
            {CATEGORY_LABELS[category] ?? category}
          </label>
        ))}
      </div>

      {submitError && (
        <div className="mt-3 rounded-lg bg-red-50 p-2 text-xs text-red-800">{submitError}</div>
      )}

      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting || !anySelected || Boolean(isActive)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {submitting ? "전송 중..." : "내보내기 시작"}
        </button>
        {isActive && (
          <span className="text-xs text-blue-700">내보내기 진행 중...</span>
        )}
        {isDone && (
          <a
            href={buildBlurExportDownloadHref(exp!.id)}
            download
            className="rounded-lg border border-green-500 bg-green-50 px-3 py-1.5 text-xs font-medium text-green-800 hover:bg-green-100"
          >
            ⬇ 레이어 다운로드
          </a>
        )}
        {isFailed && (
          <span className="text-xs text-red-700">내보내기 실패: {exp!.error ?? "알 수 없는 오류"}</span>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// BlurDetailPage — top-level container
// ============================================================================

export interface BlurDetailPageProps {
  videoId: string;
}

export function BlurDetailPage({ videoId }: BlurDetailPageProps) {
  const router = useRouter();
  // First resolve the latest blur job for this video. The list
  // endpoint is org-scoped; we pick the most recent by requested_at.
  // NB: this page uses the drive file id as ``videoId`` in the URL
  // — matching how VideoDetailPage passes it around. The blur API is
  // keyed by file_id, so we use videoId as file_id.
  const { data: list, loading: listLoading, disabled, error: listError } = useBlurJobsForFile(videoId);

  const latestJobId = useMemo(() => {
    if (!list || list.items.length === 0) return null;
    // List endpoint is already ordered by requested_at DESC.
    return list.items[0].id;
  }, [list]);

  const { data: job, loading: jobLoading, error: jobError } = useBlurJob(latestJobId);
  const { manifest } = useBlurManifest(job?.manifest_url ?? null);
  const { scenes } = useBlurScenes(videoId);

  const [playheadMs, setPlayheadMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  const handleSeek = useCallback((ms: number) => {
    setPlayheadMs(ms);
    if (videoRef.current) {
      videoRef.current.currentTime = ms / 1000;
    }
  }, []);

  const handleTogglePlay = useCallback(() => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
    setIsPlaying((v) => !v);
  }, [isPlaying]);

  useEffect(() => {
    if (disabled) {
      router.replace(`/videos/${videoId}`);
    }
  }, [disabled, router, videoId]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !isPlaying) return;
    let raf: number;
    const tick = () => {
      setPlayheadMs(video.currentTime * 1000);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [isPlaying]);

  if (listLoading || jobLoading) {
    return (
      <div className="mx-auto max-w-5xl p-6 text-sm text-gray-500">
        블러 작업을 불러오는 중...
      </div>
    );
  }

  if (listError || jobError) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <BlurHeader videoId={videoId} job={null} />
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-800">
          블러 작업을 불러올 수 없습니다: {(listError ?? jobError)?.message}
        </div>
      </div>
    );
  }

  if (!latestJobId || !job) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <BlurHeader videoId={videoId} job={null} />
        <div className="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-600">
          이 영상에 대한 블러 작업이 없습니다. 영상 상세 페이지에서 "블러 처리"를 시작해 주세요.
        </div>
      </div>
    );
  }

  const isActive = job.status === "queued" || job.status === "running";
  const isDone = job.status === "done";
  const availableCategories = job.mask_s3_keys ? Object.keys(job.mask_s3_keys) : [];

  if (!isDone) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-6">
        <BlurHeader videoId={videoId} job={job} />
        {isActive && <BlurProgressPanel job={job} />}
        {job.status === "failed" && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            블러 작업이 실패했습니다: {job.error ?? "알 수 없는 오류"}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-80px)] flex-col">
      <div className="px-6 pt-4 pb-2">
        <BlurHeader videoId={videoId} job={job} />
      </div>

      <div className="flex min-h-0 flex-1 lg:grid lg:grid-cols-[1fr_344px]">
        {/* Left: Video player */}
        <div className="flex flex-col gap-2 px-6 pb-2">
          <BlurPlayer job={job} ref={videoRef} />
        </div>

        {/* Right: Scene sidebar */}
        <div className="flex flex-col border-l border-gray-200 bg-gray-50">
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-gray-900">블러 장면</h2>
              {job.detections_summary && (
                <span className="rounded-full bg-gray-200 px-2 py-0.5 text-[10px] font-medium text-gray-700">
                  {Object.values(job.detections_summary).reduce((a, b) => a + b, 0)}
                </span>
              )}
            </div>
            {availableCategories.length > 0 && (
              <div className="flex gap-1.5">
                <button className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-[11px] text-gray-600 hover:bg-gray-50">
                  오류 신고
                </button>
                <button className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-[11px] text-gray-600 hover:bg-gray-50">
                  Premiere Export
                </button>
              </div>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-2">
            {scenes.length > 0 ? (
              scenes.map((scene) => {
                const detCount = manifest
                  ? manifest.detections.filter(
                      (d) => d.t_ms >= scene.start_ms && d.t_ms < scene.end_ms,
                    ).length
                  : 0;
                const isSceneActive =
                  playheadMs >= scene.start_ms && playheadMs < scene.end_ms;
                return (
                  <BlurSceneCard
                    key={scene.scene_id}
                    scene={scene}
                    detectionCount={detCount}
                    isActive={isSceneActive}
                    onClick={() => handleSeek(scene.start_ms)}
                  />
                );
              })
            ) : (
              <>
                {job.detections_summary && (
                  <BlurCategoryStats summary={job.detections_summary} />
                )}
              </>
            )}
            {availableCategories.length > 0 && (
              <div className="mt-2 border-t border-gray-200 pt-3">
                <BlurExportPanel jobId={job.id} availableCategories={availableCategories} />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom: Timeline */}
      <div className="shrink-0 border-t border-gray-200 px-6 py-2">
        {manifest ? (
          <BlurTimelineSection
            manifest={manifest}
            playheadMs={playheadMs}
            isPlaying={isPlaying}
            onSeek={handleSeek}
            onTogglePlay={handleTogglePlay}
          />
        ) : (
          <div className="rounded-xl border border-gray-200 bg-white p-4 text-sm text-gray-500">
            타임라인을 불러오는 중...
          </div>
        )}
      </div>
    </div>
  );
}
