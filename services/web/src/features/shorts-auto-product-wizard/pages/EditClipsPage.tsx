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
import { useSearchParams } from "next/navigation";
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getRenderJob,
  getShortComposition,
  RenderRateLimitError,
} from "@/lib/api/shorts-render";
import {
  rerenderFromEdits,
  type SubtitleEdit,
} from "@/lib/api/highlight-reel";
import { getVideoScenes } from "@/lib/api/videos";
import type { VideoScene, VideoScenesResponse } from "@/lib/types";
import { useAuth } from "@/lib/auth";

import { DEFAULT_SUBTITLE_STYLE } from "@/features/shorts-editor/constants";
import {
  createClipFromScene,
  generateSubtitlesFromTranscript,
} from "@/features/shorts-editor/hooks/useEditorState";
import type {
  EditorClip,
  EditorSubtitle,
  SubtitleStyle,
} from "@/features/shorts-editor/lib/types";

import { SubtitleEditor } from "../components/SubtitleEditor";
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
  /**
   * Backend's ``refinement_source`` flag — drives the SubtitleEditor's
   * "edits not yet rendered" banner. Set to ``'manual_edit'`` once
   * the operator has saved edits via PATCH /subtitles.
   */
  refinementSource: string | null;
}

export function EditClipsPage({ videoId, parentJobId }: Props) {
  const { getAccessToken } = useAuth();
  const searchParams = useSearchParams();

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

  // Initial clip selection from ``?clipIdx=N`` query param. The wizard's
  // per-child "스크립트 편집" button passes shorts_index-1 so the editor
  // opens on the clip the user clicked. Defaults to 0 (Clip 1).
  const initialClipIdx = useMemo(() => {
    const raw = searchParams?.get("clipIdx");
    const parsed = raw != null ? parseInt(raw, 10) : NaN;
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  }, [searchParams]);
  const [selectedClipIdx, setSelectedClipIdx] = useState(initialClipIdx);
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
  // haven't loaded yet. Note ``clipStates`` is intentionally NOT in
  // the dep array — including it caused a React race: the moment
  // this effect's first setClipStates({loading: true}) fired, the
  // effect re-ran (clipStates changed), the previous run's cleanup
  // set cancelled=true, and the async fetch's setClipStates was
  // silently dropped. State stayed stuck at {loading: true} forever.
  // Instead, the "already loaded" guard lives inside the functional
  // setState updater, which sees the freshest state without making
  // the effect react to its own writes.
  useEffect(() => {
    if (!selectedRenderJobId || !scenesByVideo) return;

    let cancelled = false;
    let alreadyLoaded = false;
    setClipStates((prev) => {
      const existing = prev[selectedRenderJobId];
      if (existing && !existing.error && !existing.loading) {
        alreadyLoaded = true;
        return prev;
      }
      return {
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
          refinementSource: null,
        },
      };
    });
    if (alreadyLoaded) {
      return;
    }

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
        }

        // Prefer the composition's actual ``subtitles[]`` — those are
        // what the renderer used to burn the captions into the MP4,
        // so the editor's panel mirrors what the operator sees in the
        // video preview. Falls back to per-scene
        // ``generateSubtitlesFromTranscript`` only when the
        // composition shipped without subtitles (legacy renders or
        // scenes that lack ``speaker_transcript``).
        const compSubtitles = extractCompositionSubtitles(compositionSpec);
        if (compSubtitles.length > 0) {
          for (const cs of compSubtitles) {
            subtitles.push({
              id: makeSubtitleId(),
              text: cs.text,
              startMs: cs.start_ms,
              endMs: cs.end_ms,
              style: cs.style ?? DEFAULT_SUBTITLE_STYLE,
            });
          }
        } else {
          for (let i = 0; i < sceneClips.length; i++) {
            const scene = sceneById.get(sceneClips[i].scene_id);
            const clip = editorClips[i];
            if (!scene || !clip) continue;
            const subs = generateSubtitlesFromTranscript(
              (scene as VideoScene).speaker_transcript,
              clip,
            );
            subtitles.push(...subs);
          }
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
            refinementSource: job.refinement_source ?? null,
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
    selectedRenderJobId, scenesByVideo, selectedClipIdx, getAccessToken, videoId,
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

  // Adapt the parent's composition.subtitles[] (snake_case JSONB) into
  // the SubtitleEditor's SubtitleEdit shape. The editor owns its own
  // state via useSubtitleEditorState — these are only the *initial*
  // cues at mount + on render-id pivot. Subsequent edits flow through
  // the editor's debounced auto-save (PATCH /subtitles), not back into
  // currentClip.subtitles. The ClipPreview overlay continues to read
  // the snapshot for orientation; that's intentional v1 — the operator
  // sees their edits authoritatively in the editor panel and on the
  // post-rerender MP4.
  const editorCues: SubtitleEdit[] = useMemo(() => {
    const comp = currentClip?.composition;
    if (!comp || typeof comp !== "object") return [];
    const subs = (comp as { subtitles?: unknown }).subtitles;
    if (!Array.isArray(subs)) return [];
    return subs.flatMap((s) => {
      if (typeof s !== "object" || s === null) return [];
      const r = s as Record<string, unknown>;
      const text = typeof r.text === "string" ? r.text : null;
      const startMs = typeof r.start_ms === "number" ? r.start_ms : null;
      const endMs = typeof r.end_ms === "number" ? r.end_ms : null;
      if (text === null || startMs === null || endMs === null) return [];
      const tid = typeof r.template_id === "string" ? r.template_id : null;
      const styleRaw = (typeof r.style === "object" && r.style !== null)
        ? (r.style as Record<string, unknown>)
        : undefined;
      return [{
        text,
        start_ms: startMs,
        end_ms: endMs,
        template_id: tid,
        style: styleRaw,
      }];
    });
  }, [currentClip?.composition]);

  const onTogglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      void v.play();
    } else {
      v.pause();
    }
  }, []);

  const onRerenderRequested = useCallback(async () => {
    if (!selectedRenderJobId) return;
    setExportError(null);
    setExportSuccess(null);
    setExportInFlight(true);
    try {
      // The SubtitleEditor's debounced auto-save has already pushed
      // the operator's edits into ``input_spec.subtitles`` via PATCH
      // /subtitles (the editor's render button is disabled while a
      // save is in flight or pending, so by the time we get here the
      // backend state is consistent). The /rerender endpoint reads
      // the parent's current input_spec server-side — no body needed.
      const child = await rerenderFromEdits(
        selectedRenderJobId,
        getAccessToken,
      );
      setExportSuccess({ jobId: child.id, downloadUrl: child.download_url });
      // Poll the new child until completed, then surface its
      // presigned download URL. The page does NOT swap the video
      // preview mid-edit (would be disorienting); operator clicks
      // the success-banner link to download the refined MP4.
      const pollId = window.setInterval(async () => {
        try {
          const fresh = await getRenderJob(child.id, getAccessToken);
          if (fresh.status === "completed" || fresh.status === "failed") {
            window.clearInterval(pollId);
            setExportSuccess({
              jobId: child.id,
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
        setExportError(err instanceof Error ? err.message : "다시 렌더링에 실패했습니다.");
      }
    } finally {
      setExportInFlight(false);
    }
  }, [selectedRenderJobId, getAccessToken]);

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
          {/*
           * Header export button removed in PR 3 of
           * auto-shorts-subtitle-editor-2026-05-06.md. The render
           * action now lives inside ``<SubtitleEditor>`` as
           * "내 편집으로 다시 렌더링" — placing it next to the cue list
           * makes the cause-and-effect (edit → render) visible.
           */}
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
          {selectedRenderJobId && currentClip && !currentClip.loading ? (
            <SubtitleEditor
              renderId={selectedRenderJobId}
              initialCues={editorCues}
              getToken={getAccessToken}
              refinementSource={currentClip.refinementSource}
              onRerenderRequested={onRerenderRequested}
              isRendering={exportInFlight}
            />
          ) : (
            <p className="text-xs text-gray-500">로딩 중...</p>
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

interface CompSubtitleShape {
  text: string;
  start_ms: number;
  end_ms: number;
  style?: SubtitleStyle;
}

function extractCompositionSubtitles(comp: unknown): CompSubtitleShape[] {
  if (typeof comp !== "object" || comp === null) return [];
  const subs = (comp as { subtitles?: unknown }).subtitles;
  if (!Array.isArray(subs)) return [];
  const out: CompSubtitleShape[] = [];
  for (const s of subs) {
    if (typeof s !== "object" || s === null) continue;
    const r = s as Record<string, unknown>;
    const text = typeof r.text === "string" ? r.text : null;
    const startMs = typeof r.start_ms === "number" ? r.start_ms : null;
    const endMs = typeof r.end_ms === "number" ? r.end_ms : null;
    if (text === null || startMs === null || endMs === null) continue;
    out.push({
      text,
      start_ms: startMs,
      end_ms: endMs,
      style: undefined,
    });
  }
  return out;
}

function makeSubtitleId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `sub_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
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
