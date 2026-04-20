"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import {
  AutoShortsFeatureDisabledError,
  AutoShortsRateLimitError,
  AutoShortsValidationError,
} from "@/lib/api/shorts-auto";
import type { ScoringModeRequest } from "@/lib/types";

import { useAutoRender } from "../hooks/useAutoRender";
import { useAutoSelect } from "../hooks/useAutoSelect";
import { useVideoMeta } from "../hooks/useVideoMeta";
import { AutoSelectPreview } from "./AutoSelectPreview";
import { ModePicker } from "./ModePicker";
import { PersonSelect } from "./PersonSelect";
import { BackArrowIcon, ChevronRightIcon, MagicWandIcon } from "./icons";

/**
 * /export/shorts/auto — orchestrator page.
 *
 * Owns all state. Delegates:
 *  - mode selection → ModePicker
 *  - person selection → PersonSelect (human mode only)
 *  - preview display → AutoSelectPreview
 *  - API calls → useAutoSelect / useAutoRender
 *  - video header → useVideoMeta
 *
 * Never imports from other feature directories. The only integration
 * points are:
 *  - query param `videoId`
 *  - redirect to `/export/shorts/editor?videoId=...&sceneIds=...` (string URL)
 *  - redirect to `/export/shorts` on successful auto-render (string URL)
 */
export function AutoShortsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { getAccessToken } = useAuth();

  const videoId = searchParams.get("videoId") ?? "";

  const [mode, setMode] = useState<ScoringModeRequest>("both");
  const [personClusterId, setPersonClusterId] = useState<string | null>(null);

  const videoMeta = useVideoMeta(videoId, getAccessToken);
  const autoSelect = useAutoSelect(getAccessToken);
  const autoRender = useAutoRender(getAccessToken);

  const videoTitle = videoMeta.meta?.video_title ?? videoId;
  const canSubmit = Boolean(videoId) && (mode !== "human" || Boolean(personClusterId));

  const handleModeChange = useCallback((next: ScoringModeRequest) => {
    setMode(next);
    if (next !== "human") {
      setPersonClusterId(null);
    }
    autoSelect.reset();
    autoRender.reset();
  }, [autoSelect, autoRender]);

  const handleGenerate = useCallback(async () => {
    if (!canSubmit || autoSelect.isLoading) return;
    await autoSelect.mutate({
      video_id: videoId,
      mode,
      person_cluster_id: mode === "human" ? personClusterId : null,
    });
  }, [canSubmit, autoSelect, videoId, mode, personClusterId]);

  const handleRender = useCallback(async () => {
    if (!canSubmit || autoRender.isLoading) return;
    const job = await autoRender.mutate({
      video_id: videoId,
      mode,
      person_cluster_id: mode === "human" ? personClusterId : null,
    });
    if (job) {
      router.push("/export/shorts");
    }
  }, [canSubmit, autoRender, videoId, mode, personClusterId, router]);

  const sceneIdsForEditor = useMemo(() => {
    const selection = autoSelect.data;
    if (!selection) return "";
    const ids: string[] = [];
    for (const clip of selection.clips) {
      for (const member of clip.members) {
        ids.push(member.scene_id);
      }
    }
    return ids.join(",");
  }, [autoSelect.data]);

  const editorHref = sceneIdsForEditor
    ? `/export/shorts/editor?videoId=${encodeURIComponent(videoId)}&sceneIds=${encodeURIComponent(sceneIdsForEditor)}`
    : "";

  const selectErrorMessage = describeError(autoSelect.error, "자동 생성에 실패했습니다.");
  const renderErrorMessage = describeError(autoRender.error, "쇼츠 렌더링 요청에 실패했습니다.");

  if (!videoId) {
    return (
      <div className="mx-auto max-w-4xl pt-4">
        <p className="text-sm text-gray-500">영상을 선택해 주세요.</p>
        <Link href="/" className="mt-4 inline-flex items-center gap-2 text-sm text-indigo-500 hover:text-indigo-600">
          <BackArrowIcon className="h-4 w-4" /> 영상 목록으로
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl pt-4">
      <nav className="mb-6 flex items-center gap-3 text-sm text-gray-500" aria-label="breadcrumb">
        <Link href="/" className="rounded-full p-1 hover:bg-gray-200" aria-label="뒤로 가기">
          <BackArrowIcon />
        </Link>
        <Link href="/" className="hover:text-gray-700">동영상 검색</Link>
        <span aria-hidden="true">&gt;</span>
        <Link href={`/videos/${videoId}`} className="hover:text-gray-700">
          {videoTitle}
        </Link>
        <span aria-hidden="true">&gt;</span>
        <span className="font-medium text-gray-700">자동 쇼츠</span>
      </nav>

      <header className="mb-6 flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-100 text-indigo-600">
          <MagicWandIcon />
        </span>
        <div>
          <h1 className="text-xl font-bold text-gray-900">자동으로 쇼츠 만들기</h1>
          <p className="text-sm text-gray-500">
            AI가 영상에서 5개의 하이라이트 클립을 선별하여 쇼츠를 만들어 드립니다.
          </p>
        </div>
      </header>

      <section className="space-y-6 rounded-xl border border-gray-200 bg-white p-6">
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-900">1. 모드 선택</h2>
          <ModePicker value={mode} onChange={handleModeChange} disabled={autoSelect.isLoading} />
        </div>

        {mode === "human" && (
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-gray-900">2. 인물 선택</h2>
            <PersonSelect
              value={personClusterId}
              onChange={(id) => setPersonClusterId(id)}
              disabled={autoSelect.isLoading}
            />
            <p className="text-xs text-gray-400">
              선택한 인물이 등장하는 장면만 쇼츠에 포함됩니다.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={!canSubmit || autoSelect.isLoading}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
              canSubmit && !autoSelect.isLoading
                ? "bg-indigo-500 text-white hover:bg-indigo-600"
                : "cursor-not-allowed bg-gray-200 text-gray-400",
            )}
          >
            {autoSelect.isLoading ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <MagicWandIcon className="h-4 w-4" />
            )}
            {autoSelect.isLoading ? "분석 중..." : "미리보기 생성"}
          </button>
          {mode === "human" && !personClusterId && (
            <span className="text-xs text-gray-500">인물을 선택한 뒤 생성할 수 있어요.</span>
          )}
        </div>

        {selectErrorMessage && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
            {selectErrorMessage}
          </p>
        )}
      </section>

      <div className="mt-6">
        <AutoSelectPreview
          videoId={videoId}
          selection={autoSelect.data}
          mode={mode}
          isLoading={autoSelect.isLoading}
        />
      </div>

      {autoSelect.data && autoSelect.data.clips.length > 0 && (
        <section className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 bg-white p-6">
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-700">마음에 드나요? 바로 렌더링하거나 타임라인에서 직접 편집할 수 있어요.</p>
            {renderErrorMessage && (
              <p role="alert" className="mt-2 text-xs text-red-600">{renderErrorMessage}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {editorHref && (
              <Link
                href={editorHref}
                className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
              >
                타임라인에서 편집
                <ChevronRightIcon className="h-4 w-4" />
              </Link>
            )}
            <button
              type="button"
              onClick={handleRender}
              disabled={autoRender.isLoading}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                autoRender.isLoading
                  ? "cursor-not-allowed bg-gray-200 text-gray-400"
                  : "bg-indigo-500 text-white hover:bg-indigo-600",
              )}
            >
              {autoRender.isLoading ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : null}
              {autoRender.isLoading ? "렌더링 요청 중..." : "바로 렌더링"}
            </button>
          </div>
        </section>
      )}
    </div>
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
