"use client";

import { cn } from "@/lib/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { reasonChipsFor, type ReasonChip } from "../lib/reason-chip-copy";
import type { AutoClipResponse } from "@/lib/types";

interface AutoClipCardProps {
  index: number;
  clip: AutoClipResponse;
  videoId: string;
}

function formatHMS(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatSeconds(ms: number): string {
  return `${Math.round(ms / 1000)}초`;
}

const CHIP_VARIANT_STYLES: Record<ReasonChip["variant"], string> = {
  success: "bg-emerald-50 text-emerald-700 border border-emerald-100",
  info: "bg-indigo-50 text-indigo-700 border border-indigo-100",
  neutral: "bg-gray-100 text-gray-700 border border-gray-200",
};

export function AutoClipCard({ index, clip, videoId }: AutoClipCardProps) {
  const { visible, overflow } = reasonChipsFor(clip.reasons, 3);
  const scorePct = Math.round(Math.min(1, Math.max(0, clip.score)) * 100);
  const representativeSceneId = clip.scene_ids[0];

  return (
    <article
      aria-label={`자동 선택 장면 ${index + 1}`}
      className="flex w-full gap-0 overflow-hidden rounded-xl border border-gray-200 bg-white"
    >
      <div className="w-[180px] flex-shrink-0">
        <SceneThumbnail
          videoId={videoId}
          sceneId={representativeSceneId}
          agentAvailable={true}
          className="aspect-video w-full"
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-bold text-gray-900">클립 {index + 1}</span>
          <div className="flex items-center gap-1.5">
            <span className="rounded-[2px] bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {formatHMS(clip.start_ms)} - {formatHMS(clip.end_ms)}
            </span>
            <span className="text-xs text-gray-500">{formatSeconds(clip.duration_ms)}</span>
          </div>
        </div>
        <div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-gray-500">매칭 점수</span>
            <span className="text-xs font-medium text-gray-700">{scorePct}%</span>
          </div>
          <div
            className="mt-1 h-1 w-full rounded-full bg-indigo-100"
            aria-hidden="true"
          >
            <div
              className="h-1 rounded-full bg-indigo-500"
              style={{ width: `${scorePct}%` }}
            />
          </div>
        </div>
        {visible.length > 0 && (
          <div className="flex flex-wrap gap-1.5" aria-label="선택 근거">
            {visible.map((chip, i) => (
              <span
                key={`${chip.raw}-${i}`}
                title={chip.raw}
                className={cn(
                  "inline-flex rounded-full px-2 py-0.5 text-[11px] leading-4",
                  CHIP_VARIANT_STYLES[chip.variant],
                )}
              >
                {chip.label}
              </span>
            ))}
            {overflow > 0 && (
              <span className="inline-flex rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-[11px] leading-4 text-gray-500">
                +{overflow}
              </span>
            )}
          </div>
        )}
        <div className="mt-auto flex items-center gap-2 text-[11px] text-gray-400">
          <span>{clip.scene_ids.length}개 장면</span>
          <span>·</span>
          <span>{clip.is_continuous ? "연속" : "선별"}</span>
        </div>
      </div>
    </article>
  );
}
