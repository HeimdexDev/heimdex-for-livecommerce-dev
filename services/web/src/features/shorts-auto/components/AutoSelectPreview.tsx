"use client";

import { AutoClipCard } from "./AutoClipCard";
import { EmptyState } from "./EmptyState";
import type { AutoSelectResponse, ScoringModeRequest } from "@/lib/types";

interface AutoSelectPreviewProps {
  videoId: string;
  selection: AutoSelectResponse | null;
  mode: ScoringModeRequest;
  isLoading: boolean;
}

export function AutoSelectPreview({
  videoId,
  selection,
  mode,
  isLoading,
}: AutoSelectPreviewProps) {
  if (isLoading) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-[320px] items-center justify-center rounded-xl border border-gray-200 bg-white"
      >
        <div className="flex flex-col items-center gap-3 text-sm text-gray-500">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-500" />
          <span>하이라이트 장면을 분석하고 있어요...</span>
        </div>
      </div>
    );
  }

  if (!selection) {
    return null;
  }

  if (selection.clips.length === 0) {
    return <EmptyState reason={selection.skipped_reason} mode={mode} />;
  }

  const totalSeconds = Math.round(selection.total_duration_ms / 1000);
  return (
    <section aria-label="자동 생성된 쇼츠 미리보기" className="space-y-4">
      <div className="flex items-center justify-between px-1">
        <h2 className="text-sm font-medium text-gray-700">
          {selection.clips.length}개 클립 · 총 {totalSeconds}초
        </h2>
      </div>
      <div className="grid gap-3">
        {selection.clips.map((clip, i) => (
          <AutoClipCard key={clip.scene_ids.join("-")} index={i} clip={clip} videoId={videoId} />
        ))}
      </div>
    </section>
  );
}
