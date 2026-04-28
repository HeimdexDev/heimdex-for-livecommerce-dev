"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useAuth } from "@/lib/auth";
import {
  AutoShortsFeatureDisabledError,
  AutoShortsRateLimitError,
  AutoShortsValidationError,
} from "@/lib/api/shorts-auto";
import type { ScoringModeRequest } from "@/lib/types";

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
import { ModeReselectModal } from "./ModeReselectModal";
import { BackArrowIcon, MagicWandIcon } from "./icons";

/**
 * /export/shorts/auto — orchestrator page (PR 3 redesign).
 *
 * Owns:
 *   - mode + person picker state (committed via the reselect modal)
 *   - selected candidate (clipKey)
 *   - render-jobs map for candidate→render-job lifecycle
 *
 * Delegates everything else to feature components. No API calls live
 * here — all go through the hooks (``useAutoSelect``,
 * ``useCandidateRenderJobs``, ``useVideoMeta``). Loose-coupling rule:
 * does not import from any other ``features/*`` directory.
 */
export function AutoShortsPage() {
  const searchParams = useSearchParams();
  const { getAccessToken } = useAuth();

  const videoId = searchParams.get("videoId") ?? "";

  const [mode, setMode] = useState<ScoringModeRequest>("both");
  const [personClusterId, setPersonClusterId] = useState<string | null>(null);
  const [selectedClipKey, setSelectedClipKey] = useState<string | null>(null);
  const [isModeModalOpen, setIsModeModalOpen] = useState(false);
  // Open the modal automatically on first land so the user actively
  // picks a mode rather than getting a default-혼합 list. This matches
  // the reference flow where the user always confirms before seeing
  // results. Skipped when there's no videoId (the page short-circuits
  // to a "select a video" message anyway).
  const [hasOpenedModeOnce, setHasOpenedModeOnce] = useState(false);

  const videoMeta = useVideoMeta(videoId, getAccessToken);
  const autoSelect = useAutoSelect(getAccessToken);
  const renderJobs = useCandidateRenderJobs(getAccessToken);

  const videoTitle = videoMeta.meta?.video_title ?? videoId;
  const scenes = videoMeta.meta?.scenes ?? [];

  // First-land: pop the modal once we have a videoId. Don't re-pop if
  // the user dismisses (they go to the empty list, can re-open via the
  // 재선택 button).
  useEffect(() => {
    if (videoId && !hasOpenedModeOnce) {
      setIsModeModalOpen(true);
      setHasOpenedModeOnce(true);
    }
  }, [videoId, hasOpenedModeOnce]);

  // Default the selected clip to the first one whenever a fresh
  // selection comes back with non-empty clips. Resets to null on
  // re-generate so the user sees a clean state.
  useEffect(() => {
    if (autoSelect.data && autoSelect.data.clips.length > 0) {
      setSelectedClipKey(clipKeyOf(autoSelect.data.clips[0]));
    } else {
      setSelectedClipKey(null);
    }
  }, [autoSelect.data]);

  const selectedClip = useMemo(() => {
    if (!autoSelect.data || !selectedClipKey) return null;
    return autoSelect.data.clips.find((c) => clipKeyOf(c) === selectedClipKey) ?? null;
  }, [autoSelect.data, selectedClipKey]);

  const buildEditorHref = useCallback(
    (sceneIds: string[]): string =>
      `/export/shorts/editor?videoId=${encodeURIComponent(videoId)}&sceneIds=${encodeURIComponent(sceneIds.join(","))}`,
    [videoId],
  );

  const runSelect = useCallback(
    async (nextMode: ScoringModeRequest, nextPerson: string | null) => {
      await autoSelect.mutate({
        video_id: videoId,
        mode: nextMode,
        person_cluster_id: nextMode === "human" ? nextPerson : null,
      });
    },
    [autoSelect, videoId],
  );

  const handleModeSubmit = useCallback(
    async (nextMode: ScoringModeRequest, nextPerson: string | null) => {
      setMode(nextMode);
      setPersonClusterId(nextPerson);
      setIsModeModalOpen(false);
      // Reset render-jobs map on re-generate — old scene_ids may not
      // exist in the new selection, and we don't want stale cards
      // sneaking back when the user picks the same scene again.
      // (The map is keyed on scene_ids.join("-"), so this is moot
      // unless the same exact scene set comes back; resetting is
      // still the safer default for v1.)
      // Intentionally not clearing renderJobs.states; stale entries
      // for scene-id sets no longer in the list are simply orphaned.
      await runSelect(nextMode, nextPerson);
    },
    [runSelect],
  );

  // Candidate card actions
  const handleDownloadCandidate = useCallback(
    async (clipKey: string) => {
      if (!autoSelect.data) return;
      const clip = autoSelect.data.clips.find((c) => clipKeyOf(c) === clipKey);
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
    [autoSelect.data, renderJobs, videoId, mode, personClusterId],
  );

  const handleDeleteCandidate = useCallback(
    async (clipKey: string) => {
      await renderJobs.remove(clipKey);
      // If the deleted card was selected, fall back to the first
      // remaining card. Render-job removal doesn't actually drop the
      // candidate from the autoSelect.data list, so just clear the
      // selection if the user wants the row gone visually we'd need a
      // separate hidden-keys set. v1 keeps the card visible (still in
      // selection.clips) but with default-candidate state restored —
      // this matches "삭제 = 렌더링 취소" rather than "삭제 = 카드 제거".
      if (selectedClipKey === clipKey) {
        // No-op — render-job-only delete; keep the same card selected.
      }
    },
    [renderJobs, selectedClipKey],
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
    <>
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
        candidateList={
          <CandidateList
            videoId={videoId}
            selection={autoSelect.data}
            mode={mode}
            isLoading={autoSelect.isLoading}
            onReselectMode={() => setIsModeModalOpen(true)}
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

      <ModeReselectModal
        open={isModeModalOpen}
        videoId={videoId}
        initialMode={mode}
        initialPersonClusterId={personClusterId}
        isLoading={autoSelect.isLoading}
        onClose={() => setIsModeModalOpen(false)}
        onSubmit={handleModeSubmit}
      />
    </>
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
