"use client";

import { useState } from "react";
import { getFaceThumbnailUrl, getCloudThumbnailUrl } from "@/lib/agent";
import type { PersonResponse } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PersonIcon } from "@/components/icons";

function ArrowRightIcon() {
  return (
    <svg
      className="h-6 w-6 text-gray-400"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"
      />
    </svg>
  );
}

function MergeAvatar({ person }: { person: PersonResponse }) {
  const [imgError, setImgError] = useState(false);
  const [useFallback, setUseFallback] = useState(false);
  const faceThumbnailUrl = getFaceThumbnailUrl(person.person_cluster_id);
  const sceneThumbnailUrl =
    person.representative_video_id && person.representative_scene_id
      ? getCloudThumbnailUrl(
          person.representative_video_id,
          person.representative_scene_id,
        )
      : null;
  const thumbnailUrl = !useFallback ? faceThumbnailUrl : sceneThumbnailUrl;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-full bg-gray-100">
        {thumbnailUrl && !imgError ? (
          <img
            src={thumbnailUrl}
            alt={person.label ?? "인물"}
            className="h-full w-full object-cover"
            onError={() => {
              if (!useFallback && sceneThumbnailUrl) {
                setUseFallback(true);
              } else {
                setImgError(true);
              }
            }}
          />
        ) : (
          <PersonIcon className="h-8 w-8 text-gray-400" />
        )}
      </div>
      <span className="max-w-[100px] truncate text-sm text-gray-700">
        {person.label || "이름 없음"}
      </span>
    </div>
  );
}

type LabelChoice = "source" | "target" | "custom";

interface MergeConfirmDialogProps {
  source: PersonResponse;
  target: PersonResponse;
  isMerging: boolean;
  onCancel: () => void;
  onConfirm: (keepLabel?: string | null) => void;
}

export function MergeConfirmDialog({
  source,
  target,
  isMerging,
  onCancel,
  onConfirm,
}: MergeConfirmDialogProps) {
  const sourceHasLabel = !!source.label;
  const targetHasLabel = !!target.label;
  const bothHaveLabels = sourceHasLabel && targetHasLabel;

  const [labelChoice, setLabelChoice] = useState<LabelChoice>(
    bothHaveLabels ? "target" : "target",
  );
  const [customLabel, setCustomLabel] = useState("");

  const resolveLabel = (): string | null | undefined => {
    if (!bothHaveLabels) {
      // If only one has a label, the backend merge_labels() picks it automatically
      return undefined;
    }
    switch (labelChoice) {
      case "target":
        return target.label;
      case "source":
        return source.label;
      case "custom":
        return customLabel.trim() || null;
    }
  };

  const handleConfirm = () => {
    onConfirm(resolveLabel());
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={isMerging ? undefined : onCancel}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !isMerging) onCancel();
        }}
        role="button"
        tabIndex={-1}
        aria-label="닫기"
      />

      <div className="relative w-[420px] rounded-xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-bold text-gray-900">인물 병합</h2>
        <p className="mt-1 text-sm text-gray-500">
          두 인물을 하나로 합칩니다. 이 작업은 되돌릴 수 없습니다.
        </p>

        {/* Avatars side-by-side */}
        <div className="mt-5 flex items-center justify-center gap-6">
          <MergeAvatar person={source} />
          <ArrowRightIcon />
          <MergeAvatar person={target} />
        </div>

        {/* Label choice — only when both have labels */}
        {bothHaveLabels && (
          <div className="mt-5">
            <p className="mb-2 text-sm font-medium text-gray-700">
              유지할 이름 선택
            </p>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="label-choice"
                  checked={labelChoice === "target"}
                  onChange={() => setLabelChoice("target")}
                  disabled={isMerging}
                  className="accent-indigo-500"
                />
                <span className="text-gray-700">{target.label}</span>
                <span className="text-xs text-gray-400">(대상)</span>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="label-choice"
                  checked={labelChoice === "source"}
                  onChange={() => setLabelChoice("source")}
                  disabled={isMerging}
                  className="accent-indigo-500"
                />
                <span className="text-gray-700">{source.label}</span>
                <span className="text-xs text-gray-400">(원본)</span>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="label-choice"
                  checked={labelChoice === "custom"}
                  onChange={() => setLabelChoice("custom")}
                  disabled={isMerging}
                  className="accent-indigo-500"
                />
                <span className="text-gray-700">직접 입력</span>
              </label>
              {labelChoice === "custom" && (
                <input
                  type="text"
                  value={customLabel}
                  onChange={(e) => setCustomLabel(e.target.value)}
                  disabled={isMerging}
                  maxLength={100}
                  placeholder="이름 입력..."
                  className="mt-1 w-full rounded border border-gray-300 px-3 py-1.5 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
              )}
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={isMerging}
            className="rounded-lg border border-gray-300 px-6 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isMerging}
            className={cn(
              "rounded-lg px-6 py-2 text-sm font-medium text-white transition-colors disabled:opacity-50",
              "bg-indigo-500 hover:bg-indigo-600",
            )}
          >
            {isMerging ? (
              <span className="flex items-center gap-2">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                병합 중...
              </span>
            ) : (
              "병합"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
