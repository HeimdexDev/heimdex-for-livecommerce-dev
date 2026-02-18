"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { getVideoScenes } from "@/lib/api/videos";
import { getAgentPlaybackUrl } from "@/lib/agent";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { formatTimestamp } from "@/lib/api/utils";
import { cn } from "@/lib/utils";
import type { VideoScene, VideoScenesResponse } from "@/lib/types";

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

function ChevronRightIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
    </svg>
  );
}

function SceneCard({
  scene,
  index,
  videoId,
  selected,
  onToggle,
}: {
  scene: VideoScene;
  index: number;
  videoId: string;
  selected: boolean;
  onToggle: () => void;
}) {
  const durationSec = Math.round((scene.end_ms - scene.start_ms) / 1000);
  const timeRange = `${formatTimestamp(scene.start_ms)} - ${formatTimestamp(scene.end_ms)}`;
  const tags = [...scene.keyword_tags, ...scene.product_tags].slice(0, 2);

  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "flex w-full gap-0 rounded-xl border overflow-hidden text-left transition-colors",
        selected
          ? "border-indigo-400 bg-indigo-50/40 ring-1 ring-indigo-400"
          : "border-gray-200 bg-white hover:border-gray-300",
      )}
    >
      <div className="w-[140px] flex-shrink-0 relative">
        <SceneThumbnail
          videoId={videoId}
          sceneId={scene.scene_id}
          agentAvailable={true}
          className="aspect-video w-full"
        />
        <div className={cn(
          "absolute top-2 left-2 flex h-5 w-5 items-center justify-center rounded border-2 transition-colors",
          selected
            ? "border-indigo-500 bg-indigo-500"
            : "border-gray-300 bg-white",
        )}>
          {selected && (
            <svg className="h-3 w-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
            </svg>
          )}
        </div>
      </div>
      <div className="flex-1 min-w-0 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-bold text-gray-900">장면{index + 1}</span>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{timeRange}</span>
            <span className="text-xs text-gray-500">{durationSec}초</span>
          </div>
        </div>
        {tags.length > 0 && (
          <div className="mt-2 flex flex-wrap justify-end gap-1.5">
            {tags.map((tag) => (
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
    </button>
  );
}

export function ShortsCreatePage() {
  const searchParams = useSearchParams();
  const { getAccessToken } = useAuth();

  const videoId = searchParams.get("videoId") ?? "";
  const sceneIdsParam = searchParams.get("sceneIds") ?? "";
  const requestedSceneIds = useMemo(
    () => new Set(sceneIdsParam.split(",").filter(Boolean)),
    [sceneIdsParam],
  );

  const router = useRouter();

  const [meta, setMeta] = useState<VideoScenesResponse | null>(null);
  const [allScenes, setAllScenes] = useState<VideoScene[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (!videoId) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);

    getVideoScenes(videoId, 200, 0, getAccessToken)
      .then((res) => {
        if (cancelled) return;
        setMeta(res);
        setAllScenes(res.scenes);
      })
      .catch(() => {
        if (cancelled) return;
        setMeta(null);
        setAllScenes([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => { cancelled = true; };
  }, [videoId, getAccessToken]);

  useEffect(() => {
    if (requestedSceneIds.size > 0 && allScenes.length > 0) {
      setSelectedIds(new Set(allScenes.filter((s) => requestedSceneIds.has(s.scene_id)).map((s) => s.scene_id)));
    }
  }, [allScenes, requestedSceneIds]);

  const selectedScenes = useMemo(
    () => allScenes.filter((s) => selectedIds.has(s.scene_id)),
    [allScenes, selectedIds],
  );

  const toggleScene = (sceneId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(sceneId)) next.delete(sceneId);
      else next.add(sceneId);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === allScenes.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(allScenes.map((s) => s.scene_id)));
    }
  };

  const handleSave = useCallback(async () => {
    if (selectedScenes.length === 0 || isSaving) return;

    setIsSaving(true);
    setSaveError(null);

    const startMs = Math.min(...selectedScenes.map((s) => s.start_ms));
    const endMs = Math.max(...selectedScenes.map((s) => s.end_ms));

    try {
      const token = await getAccessToken();
      const res = await fetch("/api/shorts", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          video_id: videoId,
          scene_ids: selectedScenes.map((s) => s.scene_id),
          title: meta?.video_title ?? null,
          start_ms: startMs,
          end_ms: endMs,
        }),
      });

      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail ?? `저장 실패 (${res.status})`);
      }

      router.push("/shorts");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "저장 중 오류가 발생했습니다.");
    } finally {
      setIsSaving(false);
    }
  }, [selectedScenes, isSaving, videoId, meta, getAccessToken, router]);

  const videoTitle = meta?.video_title || videoId;

  if (!videoId) {
    return (
      <div className="mx-auto max-w-6xl pt-4">
        <p className="text-gray-500">영상을 선택해 주세요.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl pt-4">
      <div className="mb-6 flex items-center gap-3 text-sm text-gray-500">
        <Link href="/" className="rounded-full p-1 hover:bg-gray-200">
          <BackArrowIcon />
        </Link>
        <Link href="/" className="hover:text-gray-700">전체 아카이브 검색</Link>
        <span>&gt;</span>
        <Link href={`/videos/${videoId}`} className="hover:text-gray-700">{videoTitle}</Link>
        <span>&gt;</span>
        <span className="text-gray-700 font-medium">숏츠 제작</span>
      </div>

      <div className="flex gap-8">
        <div className="w-[45%] flex-shrink-0 space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-gray-900">미리보기</h2>
              <button
                type="button"
                onClick={handleSave}
                disabled={selectedScenes.length === 0 || isSaving}
                className={cn(
                  "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
                  selectedScenes.length === 0 || isSaving
                    ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                    : "bg-indigo-500 text-white hover:bg-indigo-600",
                )}
              >
                {isSaving ? (
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                ) : (
                  <DownloadIcon />
                )}
                {isSaving ? "저장 중..." : "저장하기"}
              </button>
            </div>
            {saveError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{saveError}</p>
            )}
            <div className="aspect-[9/16] w-full overflow-hidden rounded-lg bg-black">
              <video
                src={getAgentPlaybackUrl(videoId)}
                controls
                className="h-full w-full object-contain"
              />
            </div>
          </div>

          {selectedScenes.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h2 className="text-lg font-bold text-gray-900 mb-3">
                선택된 장면 ({selectedScenes.length})
              </h2>
              <div className="space-y-2">
                {selectedScenes.map((scene, i) => (
                  <div key={scene.scene_id} className="flex items-center gap-2 text-sm text-gray-600">
                    <span className="font-medium text-gray-900">장면{allScenes.indexOf(scene) + 1}</span>
                    <span className="text-xs text-gray-400">
                      {formatTimestamp(scene.start_ms)} - {formatTimestamp(scene.end_ms)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="flex-1 min-w-0">
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-bold text-gray-900">장면 목록</h2>
                {allScenes.length > 0 && (
                  <span className="text-sm text-gray-500">
                    {selectedIds.size}/{allScenes.length} 선택
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {allScenes.length > 0 && (
                  <button
                    type="button"
                    onClick={toggleAll}
                    className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-50"
                  >
                    {selectedIds.size === allScenes.length ? "전체 해제" : "전체 선택"}
                  </button>
                )}
                <Link
                  href={`/videos/${videoId}`}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-600"
                >
                  원본 영상으로 이동
                  <ChevronRightIcon />
                </Link>
              </div>
            </div>

            <div className="space-y-3 max-h-[calc(100vh-220px)] overflow-y-auto">
              {allScenes.map((scene, i) => (
                <SceneCard
                  key={scene.scene_id}
                  scene={scene}
                  index={i}
                  videoId={videoId}
                  selected={selectedIds.has(scene.scene_id)}
                  onToggle={() => toggleScene(scene.scene_id)}
                />
              ))}
              {allScenes.length === 0 && (
                <p className="py-8 text-center text-sm text-gray-400">장면이 없습니다.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
