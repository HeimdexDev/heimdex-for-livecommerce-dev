"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { getVideoScenes } from "@/lib/api/videos";
import { getShortComposition } from "@/lib/api/shorts-render";
import type { VideoScenesResponse } from "@/lib/types";
import { useEditorState, createClipFromScene, generateSubtitlesFromTranscript } from "../hooks/useEditorState";
import { useCompositionExport } from "../hooks/useCompositionExport";
import { EditorLayout } from "./EditorLayout";
import { EditorHeader } from "./EditorHeader";
import { PreviewPanel } from "./PreviewPanel";
import { TimelinePanel } from "./TimelinePanel";
import { ClipProperties } from "./ClipProperties";
import { SubtitleStylePanel } from "./SubtitleStylePanel";
import { SceneListPanel } from "./SceneListPanel";

function BackArrowIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

export function ShortsEditorPage() {
  const searchParams = useSearchParams();
  const { getAccessToken } = useAuth();

  const videoId = searchParams.get("videoId") ?? "";
  const sceneIdsParam = searchParams.get("sceneIds") ?? "";
  const shortId = searchParams.get("shortId") ?? "";

  const [meta, setMeta] = useState<VideoScenesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [title, setTitle] = useState("");

  const editor = useEditorState();
  const {
    state,
    initFromScenes,
    initFromComposition,
    setPlayhead,
    setPlaying,
    selectSubtitle,
    updateSubtitle,
  } = editor;

  const {
    renderStatus,
    renderJob,
    renderError,
    submitComposition,
    reset: resetRender,
  } = useCompositionExport({
    state,
    title,
    getToken: getAccessToken,
  });

  const handleSubtitlePositionChange = useCallback(
    (index: number, positionX: number, positionY: number) => {
      const sub = state.subtitles[index];
      if (!sub) return;
      updateSubtitle(index, {
        style: { ...sub.style, positionX, positionY },
      });
    },
    [state.subtitles, updateSubtitle],
  );

  const handleSubtitleFontSizeChange = useCallback(
    (index: number, fontSizePx: number) => {
      const sub = state.subtitles[index];
      if (!sub) return;
      updateSubtitle(index, {
        style: { ...sub.style, fontSizePx },
      });
    },
    [state.subtitles, updateSubtitle],
  );

  // Load from scene IDs (entry from ShortsCreatePage or ShortsPlanPanel)
  useEffect(() => {
    if (!videoId || shortId) return;

    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);

    (async () => {
      try {
        const res = await getVideoScenes(videoId, 200, 0, getAccessToken);
        if (cancelled) return;

        setMeta(res);
        setTitle(res.video_title ?? "");

        const requestedIds = new Set(sceneIdsParam.split(",").filter(Boolean));
        const scenes = requestedIds.size > 0
          ? res.scenes.filter((s) => requestedIds.has(s.scene_id))
          : res.scenes;

        const sourceType = res.source_type ?? "gdrive";
        const clips = scenes.map((scene) => createClipFromScene(scene, videoId, sourceType));
        initFromScenes(videoId, sourceType, clips);
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "장면을 불러올 수 없습니다.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [videoId, sceneIdsParam, shortId, getAccessToken, initFromScenes]);

  // Load from saved short ID (entry from SavedShortsPage)
  useEffect(() => {
    if (!shortId) return;

    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);

    (async () => {
      try {
        const compRes = await getShortComposition(shortId, getAccessToken);
        if (cancelled) return;

        const comp = compRes.composition as {
          title?: string;
          scene_clips?: Array<{
            scene_id: string;
            video_id: string;
            source_type: string;
            start_ms: number;
            end_ms: number;
            timeline_start_ms: number;
            volume?: number;
          }>;
          subtitles?: Array<{
            text: string;
            start_ms: number;
            end_ms: number;
            style?: Record<string, unknown>;
          }>;
        };

        if (comp.title) setTitle(comp.title);

        const clips = (comp.scene_clips ?? []).map((sc, i) => ({
          id: `clip_loaded_${i}`,
          sceneId: sc.scene_id,
          videoId: sc.video_id,
          sourceType: sc.source_type,
          originalStartMs: sc.start_ms,
          originalEndMs: sc.end_ms,
          trimStartMs: sc.start_ms,
          trimEndMs: sc.end_ms,
          timelineStartMs: sc.timeline_start_ms,
          volume: sc.volume ?? 1.0,
        }));

        const firstClip = clips[0];
        initFromComposition({
          videoId: firstClip?.videoId ?? "",
          sourceType: firstClip?.sourceType ?? "gdrive",
          clips,
        });

        // Also fetch scenes so the scene list panel can display them
        if (firstClip?.videoId) {
          const scenesRes = await getVideoScenes(firstClip.videoId, 200, 0, getAccessToken);
          if (!cancelled) {
            setMeta(scenesRes);
            if (!comp.title) setTitle(scenesRes.video_title ?? "");
          }
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "구성을 불러올 수 없습니다.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [shortId, getAccessToken, initFromComposition]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Ignore when typing in inputs
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key === " ") {
        e.preventDefault();
        setPlaying(!state.isPlaying);
      } else if (e.key === "Delete" || e.key === "Backspace") {
        if (state.selectedClipIndex != null) {
          editor.removeClip(state.selectedClipIndex);
        } else if (state.selectedSubtitleIndex != null) {
          editor.removeSubtitle(state.selectedSubtitleIndex);
        }
      } else if (e.key === "Escape") {
        editor.selectClip(null);
        editor.selectSubtitle(null);
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [state.isPlaying, state.selectedClipIndex, state.selectedSubtitleIndex, setPlaying, editor]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-50">
        <p className="text-sm text-red-600">{loadError}</p>
        <Link href="/shorts" className="text-sm text-indigo-600 hover:text-indigo-700">
          <span className="inline-flex items-center gap-1.5">
            <BackArrowIcon />
            쇼츠 목록으로 돌아가기
          </span>
        </Link>
      </div>
    );
  }


  return (
    <div className="h-screen overflow-hidden bg-gray-100">
      <EditorHeader
        videoTitle={meta?.video_title ?? null}
        title={title}
        onTitleChange={setTitle}
        clipCount={state.clips.length}
        totalDurationMs={state.totalDurationMs}
        isDirty={state.isDirty}
        renderStatus={renderStatus}
        renderJob={renderJob}
        renderError={renderError}
        onRender={submitComposition}
        onRenderReset={resetRender}
      />

      <EditorLayout
        leftPanel={
          state.selectedClipIndex != null && state.selectedClipIndex < state.clips.length ? (
            <ClipProperties
              clip={state.clips[state.selectedClipIndex]}
              index={state.selectedClipIndex}
              onTrim={editor.trimClip}
              onVolumeChange={editor.setClipVolume}
              onRemove={editor.removeClip}
            />
          ) : (
            <SubtitleStylePanel
              title={title}
              onTitleChange={setTitle}
              videoTitle={meta?.video_title ?? null}
              subtitle={
                state.selectedSubtitleIndex != null && state.selectedSubtitleIndex < state.subtitles.length
                  ? state.subtitles[state.selectedSubtitleIndex]
                  : null
              }
              subtitleIndex={state.selectedSubtitleIndex}
              onUpdateSubtitle={editor.updateSubtitle}
              onRemoveSubtitle={editor.removeSubtitle}
            />
          )
        }
        preview={
          <PreviewPanel
            clips={state.clips}
            subtitles={state.subtitles}
            playheadMs={state.playheadMs}
            isPlaying={state.isPlaying}
            totalDurationMs={state.totalDurationMs}
            selectedSubtitleIndex={state.selectedSubtitleIndex}
            onPlayheadChange={setPlayhead}
            onPlayingChange={setPlaying}
            onSelectSubtitle={selectSubtitle}
            onUpdateSubtitlePosition={handleSubtitlePositionChange}
            onUpdateSubtitleFontSize={handleSubtitleFontSizeChange}
          />
        }
        rightPanel={
          <SceneListPanel
            videoId={state.videoId}
            scenes={meta?.scenes ?? []}
            clips={state.clips}
            selectedClipIndex={state.selectedClipIndex}
            onToggleScene={(scene) => {
              const existingIdx = state.clips.findIndex((c) => c.sceneId === scene.scene_id);
              if (existingIdx >= 0) {
                editor.removeClip(existingIdx);
              } else {
                const clip = createClipFromScene(scene, state.videoId, state.sourceType);
                editor.addClip(clip);
                const subs = generateSubtitlesFromTranscript(scene.speaker_transcript, clip);
                for (const sub of subs) {
                  editor.addSubtitle(sub);
                }
              }
            }}
            onSelectClip={editor.selectClip}
            onPreview={(clipIndex) => {
              editor.selectClip(clipIndex);
              const clip = state.clips[clipIndex];
              if (clip) setPlayhead(clip.timelineStartMs);
            }}
            onExport={submitComposition}
          />
        }
        timeline={
          <TimelinePanel
            clips={state.clips}
            subtitles={state.subtitles}
            zoom={state.zoom}
            playheadMs={state.playheadMs}
            isPlaying={state.isPlaying}
            totalDurationMs={state.totalDurationMs}
            selectedClipIndex={state.selectedClipIndex}
            selectedSubtitleIndex={state.selectedSubtitleIndex}
            onSelectClip={editor.selectClip}
            onSelectSubtitle={editor.selectSubtitle}
            onTrimClip={editor.trimClip}
            onReorderClips={editor.reorderClips}
            onUpdateSubtitle={editor.updateSubtitle}
            onAddSubtitle={editor.addSubtitle}
            onSeek={setPlayhead}
            onZoomChange={editor.setZoom}
          />
        }
      />
    </div>
  );
}
