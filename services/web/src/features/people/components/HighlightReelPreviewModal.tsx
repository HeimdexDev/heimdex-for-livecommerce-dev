"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { getCloudThumbnailUrl } from "@/lib/agent";
import {
  submitHighlightRender,
  type HighlightClipPreview,
  type HighlightReelPreviewResponse,
} from "@/lib/api/highlight-reel";

interface HighlightReelPreviewModalProps {
  isOpen: boolean;
  preview: HighlightReelPreviewResponse;
  getToken: () => Promise<string | null>;
  onClose: () => void;
  onRegenerate: () => void;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}초`;
  return seconds > 0 ? `${minutes}분 ${seconds}초` : `${minutes}분`;
}

function formatTimeRange(startMs: number, endMs: number): string {
  const fmt = (ms: number) => {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };
  return `${fmt(startMs)} - ${fmt(endMs)}`;
}

export function HighlightReelPreviewModal({
  isOpen,
  preview,
  getToken,
  onClose,
  onRegenerate,
}: HighlightReelPreviewModalProps) {
  const router = useRouter();
  const [clips, setClips] = useState<HighlightClipPreview[]>(preview.clips);
  const [title, setTitle] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const totalDuration = clips.reduce((sum, c) => sum + c.duration_ms, 0);

  const removeClip = useCallback((index: number) => {
    setClips((prev) => {
      const next = prev.filter((_, i) => i !== index);
      let cursor = 0;
      return next.map((clip) => {
        const updated = { ...clip, timeline_start_ms: cursor };
        cursor += clip.duration_ms;
        return updated;
      });
    });
  }, []);

  const handleRender = async () => {
    if (clips.length === 0) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitHighlightRender(
        preview.person_cluster_id,
        clips,
        title.trim() || null,
        getToken,
      );
      onClose();
      router.push("/shorts");
    } catch (err) {
      setError(err instanceof Error ? err.message : "렌더링 요청에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!isOpen) return null;

  // Group clips by video for display
  const groupedClips: { videoId: string; videoTitle: string | null; clips: (HighlightClipPreview & { originalIndex: number })[] }[] = [];
  clips.forEach((clip, index) => {
    const existing = groupedClips.find((g) => g.videoId === clip.video_id);
    if (existing) {
      existing.clips.push({ ...clip, originalIndex: index });
    } else {
      groupedClips.push({
        videoId: clip.video_id,
        videoTitle: clip.video_title,
        clips: [{ ...clip, originalIndex: index }],
      });
    }
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="relative mx-4 flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-gray-900">하이라이트 릴 미리보기</h3>
            <p className="mt-0.5 text-sm text-gray-500">
              {formatDuration(totalDuration)} &middot; {new Set(clips.map((c) => c.video_id)).size}개 영상
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1 text-gray-400 hover:text-gray-600">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" /></svg>
          </button>
        </div>

        {/* Clip list */}
        <div className="flex-1 overflow-y-auto px-5 py-3">
          {clips.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-400">모든 클립이 제거되었습니다.</p>
          ) : (
            <div className="space-y-4">
              {groupedClips.map((group) => (
                <div key={group.videoId}>
                  <p className="mb-1.5 text-xs font-medium text-gray-500">
                    {group.videoTitle || group.videoId}
                  </p>
                  <div className="space-y-1.5">
                    {group.clips.map((clip) => (
                      <div
                        key={`${clip.video_id}-${clip.start_ms}`}
                        className="flex items-center gap-2 rounded-md border border-gray-100 bg-gray-50 p-2"
                      >
                        <img
                          src={getCloudThumbnailUrl(clip.video_id, clip.scene_id)}
                          alt=""
                          className="h-10 w-16 flex-shrink-0 rounded object-cover"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs text-gray-700">{formatTimeRange(clip.start_ms, clip.end_ms)}</p>
                          <p className="text-xs text-gray-400">
                            {formatDuration(clip.duration_ms)}
                            {clip.run_scene_count > 1 && ` \u00b7 ${clip.run_scene_count}개 장면`}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeClip(clip.originalIndex)}
                          className="flex-shrink-0 rounded p-1 text-gray-300 hover:text-red-500"
                          aria-label="클립 제거"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" /></svg>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-100 px-5 py-4">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="제목 (선택사항)"
            maxLength={100}
            className="mb-3 w-full rounded border border-gray-200 px-3 py-1.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
          />
          {error && <p className="mb-2 text-xs text-red-500">{error}</p>}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onRegenerate}
              className="flex items-center gap-1 rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182" /></svg>
              다시 생성
            </button>
            <button
              type="button"
              onClick={handleRender}
              disabled={submitting || clips.length === 0}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-indigo-500 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : null}
              {submitting ? "요청 중..." : "렌더링 시작"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
