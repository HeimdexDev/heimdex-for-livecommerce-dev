"use client";

/**
 * Inline subtitle editor for the auto-shorts product wizard.
 *
 * Lands here from WizardStepResult's "스크립트 편집" button. Lets the
 * operator switch between Clip 1-N, edit subtitles inline, and click
 * "내보내기" to re-render the selected clip with the edits.
 *
 * Reuses primitives from the manual shorts-editor:
 *   - generateSubtitlesFromTranscript / createClipFromScene
 *   - submitRender (POST /api/shorts/render)
 *   - getShortComposition / getRenderJob (per-clip data)
 *
 * MVP cut from the screenshot mockup:
 *   - Top tabs (쇼츠 제목 / 상품 정보 / 원본 영상 제목) — not on the
 *     critical path to "edit subtitles."
 *   - Sub-tabs (레이아웃 / 요소 및 배경) — same.
 *   - Per-subtitle font/color/position controls — leverage the
 *     EditorSubtitle defaults; deferred to Phase 2.5+.
 */

import Link from "next/link";
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getRenderJob,
  getShortComposition,
  RenderRateLimitError,
  submitRender,
} from "@/lib/api/shorts-render";
import { getVideoScenes } from "@/lib/api/videos";
import type { VideoScene, VideoScenesResponse } from "@/lib/types";
import { useAuth } from "@/lib/auth";

import {
  createClipFromScene,
  generateSubtitlesFromTranscript,
} from "@/features/shorts-editor/hooks/useEditorState";
import type {
  CompositionSubtitle,
  EditorClip,
  EditorSubtitle,
} from "@/features/shorts-editor/lib/types";

import { useScanOrder } from "../hooks/useScanOrder";

interface Props {
  videoId: string;
  parentJobId: string;
}

interface ClipState {
  /** Render job id for this clip (Clip 1, Clip 2, ...). */
  renderJobId: string;
  /** 0-based index — drives Clip 1, Clip 2, ... display. */
  index: number;
  /** Title from the render job (the wizard sets these to product names). */
  title: string;
  /** Per-scene EditorClip metadata (timeline positions). One clip per scene. */
  clips: EditorClip[];
  /** Subtitles, edited locally. Initially generated from speaker_transcript. */
  subtitles: EditorSubtitle[];
  /** The render job's existing composition (used as the base for re-render). */
  composition: Record<string, unknown> | null;
  /** Presigned MP4 URL. May be null until the render finishes. */
  downloadUrl: string | null;
  /** Total duration in ms — sum of clip trim ranges. */
  totalDurationMs: number;
  /** Loading state for first-fetch. */
  loading: boolean;
  /** Per-clip error message. */
  error: string | null;
}

export function EditClipsPage({ videoId, parentJobId }: Props) {
  const { getAccessToken } = useAuth();

  const scanOrder = useScanOrder(parentJobId, getAccessToken);

  const children = useMemo(
    () => scanOrder.status?.children ?? [],
    [scanOrder.status?.children],
  );

  const sortedChildren = useMemo(() => {
    return [...children]
      .filter((c) => Boolean(c.render_job_id))
      .sort((a, b) => (a.shorts_index ?? 0) - (b.shorts_index ?? 0));
  }, [children]);

  const [selectedClipIdx, setSelectedClipIdx] = useState(0);
  const [scenesByVideo, setScenesByVideo] = useState<VideoScenesResponse | null>(null);
  const [scenesError, setScenesError] = useState<string | null>(null);
  const [clipStates, setClipStates] = useState<Record<string, ClipState>>({});
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportInFlight, setExportInFlight] = useState(false);
  const [exportSuccess, setExportSuccess] = useState<{ jobId: string; downloadUrl: string | null } | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playheadMs, setPlayheadMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  // Fetch scenes once for the page.
  useEffect(() => {
    if (!videoId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getVideoScenes(videoId, 200, 0, getAccessToken);
        if (!cancelled) setScenesByVideo(res);
      } catch (err) {
        if (!cancelled) {
          setScenesError(err instanceof Error ? err.message : "장면을 불러올 수 없습니다.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [videoId, getAccessToken]);

  const selectedChild = sortedChildren[selectedClipIdx];
  const selectedRenderJobId = selectedChild?.render_job_id ?? null;

  // Lazy-load per-clip data when the user switches to a clip we
  // haven't loaded yet.
  useEffect(() => {
    if (!selectedRenderJobId || !scenesByVideo) return;
    const existing = clipStates[selectedRenderJobId];
    if (existing && !existing.error) return;

    let cancelled = false;
    setClipStates((prev) => ({
      ...prev,
      [selectedRenderJobId]: {
        renderJobId: selectedRenderJobId,
        index: selectedClipIdx,
        title: "",
        clips: [],
        subtitles: [],
        composition: null,
        downloadUrl: null,
        totalDurationMs: 0,
        loading: true,
        error: null,
      },
    }));

    (async () => {
      try {
        const [comp, job] = await Promise.all([
          getShortComposition(selectedRenderJobId, getAccessToken),
          getRenderJob(selectedRenderJobId, getAccessToken),
        ]);
        if (cancelled) return;

        const compositionSpec = comp.composition;
        const sceneClips = extractSceneClips(compositionSpec);
        const compTitle = extractTitle(compositionSpec) ?? job.title ?? "";
        const sourceType = scenesByVideo.source_type ?? "gdrive";

        const editorClips: EditorClip[] = [];
        const subtitles: EditorSubtitle[] = [];
        const sceneById = new Map(scenesByVideo.scenes.map((s) => [s.scene_id, s]));

        for (const sc of sceneClips) {
          const scene = sceneById.get(sc.scene_id);
          if (!scene) continue;
          const clip = createClipFromScene(scene as VideoScene, videoId, sourceType);
          editorClips.push(clip);
          const subs = generateSubtitlesFromTranscript(
            (scene as VideoScene).speaker_transcript,
            clip,
          );
          subtitles.push(...subs);
        }

        const totalDurationMs = editorClips.reduce(
          (acc, c) => acc + (c.trimEndMs - c.trimStartMs),
          0,
        );

        setClipStates((prev) => ({
          ...prev,
          [selectedRenderJobId]: {
            renderJobId: selectedRenderJobId,
            index: selectedClipIdx,
            title: compTitle,
            clips: editorClips,
            subtitles,
            composition: compositionSpec,
            downloadUrl: job.download_url,
            totalDurationMs,
            loading: false,
            error: null,
          },
        }));
      } catch (err) {
        if (cancelled) return;
        setClipStates((prev) => ({
          ...prev,
          [selectedRenderJobId]: {
            ...(prev[selectedRenderJobId] ?? ({} as ClipState)),
            renderJobId: selectedRenderJobId,
            index: selectedClipIdx,
            loading: false,
            error: err instanceof Error ? err.message : "클립을 불러올 수 없습니다.",
          },
        }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    selectedRenderJobId, scenesByVideo, selectedClipIdx, clipStates, getAccessToken, videoId,
  ]);

  // Reset playback state when switching clips.
  useEffect(() => {
    setPlayheadMs(0);
    setIsPlaying(false);
    if (videoRef.current) {
      videoRef.current.currentTime = 0;
      videoRef.current.pause();
    }
  }, [selectedClipIdx]);

  const currentClip = selectedRenderJobId ? clipStates[selectedRenderJobId] : undefined;

  const onUpdateSubtitle = useCallback(
    (idx: number, updates: Partial<EditorSubtitle>) => {
      if (!selectedRenderJobId || !currentClip) return;
      const next = currentClip.subtitles.map((s, i) =>
        i === idx ? { ...s, ...updates } : s,
      );
      setClipStates((prev) => ({
        ...prev,
        [selectedRenderJobId]: { ...currentClip, subtitles: next },
      }));
    },
    [selectedRenderJobId, currentClip],
  );

  const onTogglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      void v.play();
    } else {
      v.pause();
    }
  }, []);

  const onExport = useCallback(async () => {
    if (!currentClip || !selectedRenderJobId) return;
    setExportError(null);
    setExportSuccess(null);
    setExportInFlight(true);
    try {
      const baseComp = currentClip.composition ?? {};
      const subs: CompositionSubtitle[] = currentClip.subtitles.map((s) => ({
        text: s.text,
        start_ms: s.startMs,
        end_ms: s.endMs,
        style: {
          font_family: s.style.fontFamily,
          font_size_px: s.style.fontSizePx,
          font_color: s.style.fontColor,
          font_weight: s.style.fontWeight,
          position_x: s.style.positionX,
          position_y: s.style.positionY,
          background_color: s.style.backgroundColor ?? null,
          background_opacity: s.style.backgroundOpacity ?? null,
        },
      }));
      const composition = { ...baseComp, subtitles: subs };
      const job = await submitRender(
        composition,
        videoId,
        currentClip.title || null,
        getAccessToken,
      );
      // Poll the render job for completion. Mirrors the manual
      // editor's useCompositionExport polling cadence.
      setExportSuccess({ jobId: job.id, downloadUrl: job.download_url });
      const pollId = window.setInterval(async () => {
        try {
          const fresh = await getRenderJob(job.id, getAccessToken);
          if (fresh.status === "completed" || fresh.status === "failed") {
            window.clearInterval(pollId);
            setExportSuccess({
              jobId: job.id,
              downloadUrl: fresh.download_url,
            });
          }
        } catch {
          window.clearInterval(pollId);
        }
      }, 3000);
    } catch (err) {
      if (err instanceof RenderRateLimitError) {
        setExportError("잠시 후 다시 시도해주세요. (요청이 많습니다)");
      } else {
        setExportError(err instanceof Error ? err.message : "내보내기에 실패했습니다.");
      }
    } finally {
      setExportInFlight(false);
    }
  }, [currentClip, selectedRenderJobId, videoId, getAccessToken]);

  if (scanOrder.error) {
    return <ErrorState message={`클립 정보를 불러올 수 없습니다: ${scanOrder.error.message}`} />;
  }
  if (scenesError) {
    return <ErrorState message={`장면 정보를 불러올 수 없습니다: ${scenesError}`} />;
  }
  if (!scanOrder.status || sortedChildren.length === 0) {
    return <LoadingState />;
  }

  const headerHash = parentJobId.replace(/-/g, "").slice(0, 32);

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      <div className="flex items-center justify-between border-b bg-white px-6 py-3">
        <Link
          href={`/export/shorts/auto/wizard/${videoId}/result/${parentJobId}`}
          className="text-sm text-gray-700 hover:text-indigo-600"
        >
          ← 뒤로가기
        </Link>
        <div className="text-sm font-medium text-gray-700">
          Heimdex Mini · {headerHash}
        </div>
        <div className="flex items-center gap-2">
          <Link
            href={`/export/shorts/auto/wizard/${videoId}/select-product?length=60&count=5&distribution=single&language=ko&intent=commit`}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
          >
            새 쇼츠
          </Link>
          <button
            type="button"
            onClick={() => void onExport()}
            disabled={exportInFlight || !currentClip || currentClip.loading}
            className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-gray-400"
          >
            {exportInFlight ? "내보내는 중..." : "내보내기"}
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex flex-1 items-center justify-center p-8">
          {currentClip?.loading ? (
            <div className="text-sm text-gray-500">로딩 중...</div>
          ) : currentClip?.error ? (
            <div className="text-sm text-red-700">{currentClip.error}</div>
          ) : currentClip?.downloadUrl ? (
            <ClipPreview
              ref={videoRef}
              src={currentClip.downloadUrl}
              subtitles={currentClip.subtitles}
              playheadMs={playheadMs}
              onPlayheadChange={setPlayheadMs}
              onPlayingChange={setIsPlaying}
            />
          ) : (
            <div className="text-sm text-gray-500">렌더 결과가 아직 준비되지 않았습니다.</div>
          )}
        </div>

        <div className="w-[420px] overflow-y-auto border-l bg-white p-4">
          <div className="mb-2 flex gap-1 rounded bg-gray-100 p-1 text-xs">
            <span className="flex-1 rounded bg-white px-2 py-1 text-center font-medium">자막</span>
          </div>
          <h3 className="mb-2 text-sm font-semibold">자동 자막</h3>
          {currentClip?.subtitles.length === 0 ? (
            <p className="text-xs text-gray-500">이 클립에는 발화 자막이 없습니다.</p>
          ) : (
            <ul className="space-y-3">
              {currentClip?.subtitles.map((sub, idx) => (
                <li key={sub.id} className="space-y-1">
                  <div className="text-[11px] text-gray-500">
                    {fmtMs(sub.startMs)} - {fmtMs(sub.endMs)}
                  </div>
                  <textarea
                    value={sub.text}
                    onChange={(e) => onUpdateSubtitle(idx, { text: e.target.value })}
                    className="w-full resize-y rounded border border-gray-300 px-2 py-1 text-sm focus:border-indigo-500 focus:outline-none"
                    rows={2}
                  />
                </li>
              ))}
            </ul>
          )}
          {exportError ? (
            <p className="mt-3 rounded bg-red-50 p-2 text-xs text-red-700">{exportError}</p>
          ) : null}
          {exportSuccess ? (
            <div className="mt-3 rounded bg-green-50 p-2 text-xs text-green-800">
              {exportSuccess.downloadUrl ? (
                <a
                  href={exportSuccess.downloadUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium underline"
                >
                  렌더링 완료 — 다운로드
                </a>
              ) : (
                <>렌더링 중... ({exportSuccess.jobId.slice(0, 8)})</>
              )}
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-3 border-t bg-white px-6 py-3">
        <button
          type="button"
          onClick={onTogglePlay}
          disabled={!currentClip?.downloadUrl}
          className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-gray-400"
        >
          {isPlaying ? "일시정지" : "재생"}
        </button>
        <div className="text-xs text-gray-600">
          {fmtMs(playheadMs)} / {fmtMs(currentClip?.totalDurationMs ?? 0)}
        </div>
        <div className="ml-4 flex gap-2">
          {sortedChildren.map((child, idx) => (
            <button
              type="button"
              key={child.job_id}
              onClick={() => setSelectedClipIdx(idx)}
              className={`rounded px-3 py-1 text-sm ${
                idx === selectedClipIdx
                  ? "bg-indigo-600 text-white"
                  : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
              }`}
            >
              Clip {idx + 1}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ────────────── helpers ──────────────

function fmtMs(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function extractSceneClips(comp: unknown): { scene_id: string }[] {
  if (typeof comp !== "object" || comp === null) return [];
  const sc = (comp as { scene_clips?: unknown }).scene_clips;
  if (!Array.isArray(sc)) return [];
  return sc.flatMap((c) => {
    if (typeof c !== "object" || c === null) return [];
    const sceneId = (c as { scene_id?: unknown }).scene_id;
    return typeof sceneId === "string" ? [{ scene_id: sceneId }] : [];
  });
}

function extractTitle(comp: unknown): string | null {
  if (typeof comp !== "object" || comp === null) return null;
  const t = (comp as { title?: unknown }).title;
  return typeof t === "string" ? t : null;
}

// ────────────── tiny components ──────────────

interface ClipPreviewProps {
  src: string;
  subtitles: EditorSubtitle[];
  playheadMs: number;
  onPlayheadChange: (ms: number) => void;
  onPlayingChange: (playing: boolean) => void;
}

const ClipPreview = forwardRef<HTMLVideoElement, ClipPreviewProps>(
  function ClipPreview(
    { src, subtitles, playheadMs, onPlayheadChange, onPlayingChange },
    ref,
  ) {
    const active = subtitles.filter(
      (s) => playheadMs >= s.startMs && playheadMs < s.endMs,
    );
    return (
      <div className="relative aspect-[9/16] h-full max-h-[80vh] overflow-hidden rounded-lg bg-black">
        <video
          ref={ref}
          src={src}
          className="h-full w-full object-contain"
          controls
          onTimeUpdate={(e) =>
            onPlayheadChange(Math.floor((e.currentTarget.currentTime || 0) * 1000))
          }
          onPlay={() => onPlayingChange(true)}
          onPause={() => onPlayingChange(false)}
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-12 flex justify-center">
          {active.map((s) => (
            <div
              key={s.id}
              className="rounded bg-black/70 px-3 py-1 text-sm font-medium text-white"
              style={{ fontFamily: s.style.fontFamily }}
            >
              {s.text}
            </div>
          ))}
        </div>
      </div>
    );
  },
);

function LoadingState() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-2 p-6 text-center">
      <p className="text-sm text-red-700">{message}</p>
    </div>
  );
}
