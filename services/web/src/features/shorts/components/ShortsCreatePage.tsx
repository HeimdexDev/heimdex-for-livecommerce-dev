"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { getVideoScenes } from "@/lib/api/videos";
import { getAgentPlaybackUrl, getCloudPlaybackUrl } from "@/lib/agent";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { cn } from "@/lib/utils";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";
import type { VideoScene, VideoScenesResponse } from "@/lib/types";

const SPEAKER_BADGE_COLORS = ["bg-red-500", "bg-blue-500", "bg-green-500", "bg-amber-500"];

function formatTimestampHMS(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function speakerTimestampToAbsoluteHMS(ts: string, sceneStartMs: number): string {
  const parts = ts.split(":").map(Number);
  let offsetSeconds: number;
  if (parts.length === 2) {
    offsetSeconds = parts[0] * 60 + parts[1];
  } else {
    offsetSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
  }
  const absoluteMs = sceneStartMs + offsetSeconds * 1000;
  return formatTimestampHMS(absoluteMs);
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

function ChevronRightIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
    </svg>
  );
}

export function SceneCard({
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
  const timeRange = `${formatTimestampHMS(scene.start_ms)} - ${formatTimestampHMS(scene.end_ms)}`;
  const tags = [...scene.keyword_tags, ...scene.product_tags].slice(0, 2);
  const speakerEntries = parseSpeakerTranscript(scene.speaker_transcript ?? "");

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
      <div className="w-[140px] flex-shrink-0">
        <SceneThumbnail
          videoId={videoId}
          sceneId={scene.scene_id}
          agentAvailable={true}
          className="aspect-video w-full"
        />
      </div>
      <div className="flex-1 min-w-0 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-bold text-gray-900">장면{index + 1}</span>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <span className="rounded-[2px] bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{timeRange}</span>
              <span className="text-xs text-gray-500">{durationSec}초</span>
            </div>
            <div
              data-testid="scene-checkbox"
              className={cn(
                "flex items-center justify-center size-[16.5px] rounded-[4px] transition-colors",
                selected
                  ? "bg-[#605dec]"
                  : "bg-white border-[0.688px] border-[#c7c7c7]",
              )}
            >
              {selected && (
                <svg className="h-2.5 w-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                </svg>
              )}
            </div>
          </div>
        </div>
        {scene.scene_caption && (
          <p className="mt-1.5 text-xs text-gray-600">
            {scene.scene_caption.length > 70
              ? scene.scene_caption.slice(0, 70) + "…"
              : scene.scene_caption}
          </p>
        )}
        {speakerEntries.length > 0 ? (
          <div className="mt-2 space-y-2">
            {speakerEntries.slice(0, 2).map((entry, i) => (
              <div key={i} className="flex items-start gap-2">
                <span
                  className={cn(
                    "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white",
                    SPEAKER_BADGE_COLORS[entry.label.charCodeAt(0) - 65] ?? "bg-gray-400",
                  )}
                >
                  {entry.label}
                </span>
                <span className="flex-shrink-0 text-xs text-gray-400">
                  {entry.timestamp ? speakerTimestampToAbsoluteHMS(entry.timestamp, scene.start_ms) : ""}
                </span>
                <span className="text-xs text-gray-600 line-clamp-3">
                  {entry.text.length > 100 ? entry.text.slice(0, 100) + "…" : entry.text}
                </span>
              </div>
            ))}
          </div>
        ) : scene.transcript_raw ? (
          <p className="mt-1 text-xs text-gray-400">
            {scene.transcript_raw.length > 100
              ? scene.transcript_raw.slice(0, 100) + "…"
              : scene.transcript_raw}
          </p>
        ) : null}
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
        <Link href="/" className="hover:text-gray-700">동영상 검색</Link>
        <span>&gt;</span>
        <Link href={`/videos/${videoId}`} className="hover:text-gray-700">{videoTitle}</Link>
        <span>&gt;</span>
        <span className="text-gray-700 font-medium">쇼츠 제작</span>
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
                src={meta?.source_type === "gdrive" ? getCloudPlaybackUrl(videoId) : getAgentPlaybackUrl(videoId)}
                controls
                className="h-full w-full object-contain"
              />
            </div>
          </div>

          {selectedScenes.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-bold text-gray-900">
                  선택된 장면 ({selectedScenes.length})
                </h2>
                <Link
                  href={`/shorts/editor?videoId=${videoId}&sceneIds=${selectedScenes.map((s) => s.scene_id).join(",")}`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
                >
                  타임라인에서 편집
                  <ChevronRightIcon />
                </Link>
              </div>
              <div className="space-y-2">
                {selectedScenes.map((scene, i) => (
                  <div key={scene.scene_id} className="flex items-center gap-2 text-sm text-gray-600">
                    <span className="font-medium text-gray-900">장면{allScenes.indexOf(scene) + 1}</span>
                    <span className="text-xs text-gray-400">
                      {formatTimestampHMS(scene.start_ms)} - {formatTimestampHMS(scene.end_ms)}
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
