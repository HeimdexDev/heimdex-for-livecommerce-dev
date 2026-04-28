"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/lib/auth";
import {
  AutoShortsFeatureDisabledError,
  AutoShortsRateLimitError,
  AutoShortsValidationError,
} from "@/lib/api/shorts-auto";
import type { AutoSelectResponse, ScoringModeRequest } from "@/lib/types";

import { useAutoSelect } from "../hooks/useAutoSelect";
import { useVideoMeta } from "../hooks/useVideoMeta";
import {
  clipKeyOf,
  useCandidateRenderJobs,
} from "../hooks/useCandidateRenderJobs";
import { AutoShortsLayout } from "./AutoShortsLayout";
import { CandidateList } from "./CandidateList";
import { CenterPlayer } from "./CenterPlayer";
import { InspectorPanel } from "./InspectorPanel";
import { ModeTabs } from "./ModeTabs";
import { BackArrowIcon, MagicWandIcon } from "./icons";

/**
 * /export/shorts/auto — orchestrator page (PR 5: mode tabs).
 *
 * Owns:
 *   - mode + person picker state (driven by the in-page tab strip)
 *   - per-(videoId, mode, personClusterId) cache of AutoSelectResponse
 *     so flipping back to a previously-seen tab is instant
 *   - selected candidate (clipKey)
 *   - render-jobs map for candidate→render-job lifecycle
 *
 * No API calls live here — all go through the hooks (``useAutoSelect``,
 * ``useCandidateRenderJobs``, ``useVideoMeta``). Loose-coupling rule:
 * does not import from any other ``features/*`` directory.
 *
 * Behavior change from PR 3:
 *   - Removed the first-land modal. With tabs always visible, the user
 *     lands and sees results for the default 혼합 tab immediately.
 *   - Switching tabs is cache-aware: if the user has already generated
 *     for the new (mode, personClusterId) tuple, results render
 *     instantly. Cache miss triggers a fresh auto-select.
 *   - 인물 중심 with no person picked stays in a "waiting for person"
 *     state — the inline picker is rendered by ``ModeTabs``; this
 *     page suppresses generation until a person resolves.
 */
function cacheKeyOf(
  videoId: string,
  mode: ScoringModeRequest,
  personClusterId: string | null,
): string {
  return `${videoId}|${mode}|${personClusterId ?? ""}`;
}

export function AutoShortsPage() {
  const searchParams = useSearchParams();
  const { getAccessToken } = useAuth();

  const videoId = searchParams.get("videoId") ?? "";

  const [mode, setMode] = useState<ScoringModeRequest>("both");
  const [personClusterId, setPersonClusterId] = useState<string | null>(null);
  const [selectedClipKey, setSelectedClipKey] = useState<string | null>(null);
  // currentSelection is a presentation-layer copy of an
  // AutoSelectResponse — sourced either from the live mutation or from
  // the per-tuple cache. Decoupled from useAutoSelect.data so cache
  // hits don't require triggering a no-op mutation.
  const [currentSelection, setCurrentSelection] = useState<AutoSelectResponse | null>(null);
  // Per-(videoId, mode, personClusterId) result cache. useRef so cache
  // mutations don't trigger renders; renders are driven by the
  // currentSelection state set when reading FROM cache.
  const cacheRef = useRef<Map<string, AutoSelectResponse>>(new Map());

  const videoMeta = useVideoMeta(videoId, getAccessToken);
  const autoSelect = useAutoSelect(getAccessToken);
  const renderJobs = useCandidateRenderJobs(getAccessToken);

  const videoTitle = videoMeta.meta?.video_title ?? videoId;
  const scenes = videoMeta.meta?.scenes ?? [];

  // Default the selected clip to the first one whenever a fresh
  // selection comes through (live mutation or cache swap). Resets to
  // null when there are no clips so the empty/loading states get
  // displayed cleanly.
  useEffect(() => {
    if (currentSelection && currentSelection.clips.length > 0) {
      setSelectedClipKey(clipKeyOf(currentSelection.clips[0]));
    } else {
      setSelectedClipKey(null);
    }
  }, [currentSelection]);

  const selectedClip = useMemo(() => {
    if (!currentSelection || !selectedClipKey) return null;
    return currentSelection.clips.find((c) => clipKeyOf(c) === selectedClipKey) ?? null;
  }, [currentSelection, selectedClipKey]);

  const buildEditorHref = useCallback(
    (sceneIds: string[]): string =>
      `/export/shorts/editor?videoId=${encodeURIComponent(videoId)}&sceneIds=${encodeURIComponent(sceneIds.join(","))}`,
    [videoId],
  );

  const runSelect = useCallback(
    async (nextMode: ScoringModeRequest, nextPerson: string | null) => {
      const key = cacheKeyOf(videoId, nextMode, nextPerson);
      const result = await autoSelect.mutate({
        video_id: videoId,
        mode: nextMode,
        person_cluster_id: nextMode === "human" ? nextPerson : null,
      });
      if (result) {
        cacheRef.current.set(key, result);
        setCurrentSelection(result);
      } else {
        // Failure path — keep currentSelection as-is so the user can
        // still see prior results; the page header shows the error.
      }
    },
    [autoSelect, videoId],
  );

  // First-land auto-fire: the moment we have a videoId, kick off
  // generation for the default 혼합 tab so the user sees results
  // without an extra click. PR 3's modal was the gate that prevented
  // this; with tabs as the picker, no gate.
  const hasFiredFirstLandRef = useRef(false);
  useEffect(() => {
    if (!videoId || hasFiredFirstLandRef.current) return;
    hasFiredFirstLandRef.current = true;
    void runSelect(mode, personClusterId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  const handleModeChange = useCallback(
    async (next: ScoringModeRequest) => {
      // Switching to a tab where person mode requires a pick: clear
      // selection but DO NOT fire mutate — wait for the person.
      const nextPerson = next === "human" ? personClusterId : null;
      setMode(next);
      // Clear non-applicable person on non-human modes so the cache
      // key normalizes; the picker will hold its prior selection if
      // user flips back to 인물 중심.
      const lookupPerson = next === "human" ? personClusterId : null;
      const key = cacheKeyOf(videoId, next, lookupPerson);
      const cached = cacheRef.current.get(key);
      if (cached) {
        setCurrentSelection(cached);
        return;
      }
      if (next === "human" && !nextPerson) {
        // Wait for person — picker is inline, page shows empty state.
        setCurrentSelection(null);
        return;
      }
      await runSelect(next, lookupPerson);
    },
    [personClusterId, runSelect, videoId],
  );

  const handlePersonChange = useCallback(
    async (next: string | null) => {
      setPersonClusterId(next);
      // Person change only matters in human mode. In other modes the
      // picker isn't visible so this is unreachable, but guard
      // anyway so the cache key isn't polluted.
      if (mode !== "human") return;
      if (!next) {
        setCurrentSelection(null);
        return;
      }
      const key = cacheKeyOf(videoId, mode, next);
      const cached = cacheRef.current.get(key);
      if (cached) {
        setCurrentSelection(cached);
        return;
      }
      await runSelect(mode, next);
    },
    [mode, runSelect, videoId],
  );

  // Candidate card actions
  const handleDownloadCandidate = useCallback(
    async (clipKey: string) => {
      if (!currentSelection) return;
      const clip = currentSelection.clips.find((c) => clipKeyOf(c) === clipKey);
      if (!clip) return;

      const state = renderJobs.getState(clipKey);
      if (state.kind === "candidate" || state.kind === "failed") {
        await renderJobs.startRender(clipKey, {
          videoId,
          mode,
          personClusterId,
          title: null,
          clip,
        });
        return;
      }
      if (state.kind === "completed") {
        const filename = `auto-shorts-${clipKey.slice(0, 24)}.mp4`;
        await renderJobs.download(clipKey, filename);
      }
      // queued/rendering/submitting: button is disabled in the card.
    },
    [currentSelection, renderJobs, videoId, mode, personClusterId],
  );

  const handleDeleteCandidate = useCallback(
    async (clipKey: string) => {
      await renderJobs.remove(clipKey);
    },
    [renderJobs],
  );

  const inspectorIsDownloading = useMemo(() => {
    if (!selectedClipKey) return false;
    const state = renderJobs.getState(selectedClipKey);
    return (
      state.kind === "submitting" ||
      state.kind === "queued" ||
      state.kind === "rendering"
    );
  }, [renderJobs, selectedClipKey]);

  const selectErrorMessage = describeError(
    autoSelect.error,
    "자동 생성에 실패했습니다.",
  );

  if (!videoId) {
    return (
      <div className="mx-auto max-w-4xl pt-4">
        <p className="text-sm text-gray-500">영상을 선택해 주세요.</p>
        <Link
          href="/"
          className="mt-4 inline-flex items-center gap-2 text-sm text-indigo-500 hover:text-indigo-600"
        >
          <BackArrowIcon className="h-4 w-4" /> 영상 목록으로
        </Link>
      </div>
    );
  }

  return (
    <AutoShortsLayout
      header={
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <nav
              className="mb-1 flex items-center gap-2 text-xs text-gray-500"
              aria-label="breadcrumb"
            >
              <Link
                href="/"
                className="rounded-full p-1 hover:bg-gray-200"
                aria-label="뒤로 가기"
              >
                <BackArrowIcon className="h-4 w-4" />
              </Link>
              <Link href="/" className="hover:text-gray-700">
                동영상 검색
              </Link>
              <span aria-hidden="true">&gt;</span>
              <Link
                href={`/videos/${videoId}`}
                className="truncate hover:text-gray-700"
              >
                {videoTitle}
              </Link>
              <span aria-hidden="true">&gt;</span>
              <span className="font-medium text-gray-700">자동 쇼츠</span>
            </nav>
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-indigo-100 text-indigo-600">
                <MagicWandIcon className="h-4 w-4" />
              </span>
              <h1 className="truncate text-base font-bold text-gray-900">
                자동으로 쇼츠 만들기
              </h1>
            </div>
          </div>
          {selectErrorMessage && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-1.5 text-xs text-red-600"
            >
              {selectErrorMessage}
            </p>
          )}
        </div>
      }
      modeBar={
        <ModeTabs
          videoId={videoId}
          mode={mode}
          personClusterId={personClusterId}
          isLoading={autoSelect.isLoading}
          onModeChange={handleModeChange}
          onPersonChange={handlePersonChange}
        />
      }
      candidateList={
        <CandidateList
          videoId={videoId}
          selection={currentSelection}
          mode={mode}
          isLoading={autoSelect.isLoading}
          selectedClipKey={selectedClipKey}
          onSelectClip={setSelectedClipKey}
          onDownloadClip={handleDownloadCandidate}
          onDeleteClip={handleDeleteCandidate}
          getState={renderJobs.getState}
          buildEditorHref={buildEditorHref}
        />
      }
      player={
        <CenterPlayer
          clip={selectedClip}
          videoId={videoId}
          isLoadingSelection={autoSelect.isLoading}
        />
      }
      inspector={
        <InspectorPanel
          clip={selectedClip}
          scenes={scenes}
          editorHref={
            selectedClip ? buildEditorHref(selectedClip.scene_ids) : null
          }
          onDownload={
            selectedClipKey
              ? () => handleDownloadCandidate(selectedClipKey)
              : undefined
          }
          isDownloading={inspectorIsDownloading}
        />
      }
    />
  );
}

function describeError(err: Error | null, fallback: string): string | null {
  if (!err) return null;
  if (err instanceof AutoShortsRateLimitError) {
    return "시간당 생성 한도에 도달했습니다. 잠시 뒤 다시 시도해 주세요.";
  }
  if (err instanceof AutoShortsFeatureDisabledError) {
    return "이 기능은 현재 사용할 수 없습니다.";
  }
  if (err instanceof AutoShortsValidationError) {
    return err.message;
  }
  return err.message || fallback;
}
