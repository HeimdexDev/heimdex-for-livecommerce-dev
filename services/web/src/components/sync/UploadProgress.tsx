"use client";

import { cn } from "@/lib/utils";

type UploadState = "uploading" | "paused" | "complete" | "error" | "hidden";

interface UploadProgressProps {
  state: UploadState;
  progress: number;
  statusText?: string;
  onStop: () => void;
  onPause: () => void;
  onResume: () => void;
  onClose: () => void;
}

function StopIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
      <rect x="4" y="4" width="12" height="12" rx="1" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
      <rect x="5" y="3" width="3.5" height="14" rx="1" />
      <rect x="11.5" y="3" width="3.5" height="14" rx="1" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
      <path d="M6 4l10 6-10 6V4z" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      className="h-5 w-5"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
  );
}

export function UploadProgress({
  state,
  progress,
  statusText,
  onStop,
  onPause,
  onResume,
  onClose,
}: UploadProgressProps) {
  if (state === "hidden") return null;

  if (state === "complete") {
    return (
      <div className="fixed right-8 top-20 z-50 w-[280px] rounded-xl bg-gray-800 p-5 shadow-lg">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-3xl font-bold text-white">100%</p>
            <p className="mt-1 text-sm text-white">
              업로드 완료{" "}
              <span className="text-green-400">✓</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 transition-colors hover:text-white"
          >
            <CloseIcon />
          </button>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="fixed right-8 top-20 z-50 w-[280px] rounded-xl bg-white p-5 shadow-lg ring-1 ring-red-200">
        <div className="flex items-start justify-between">
          <p className="text-sm font-medium text-red-600">
            {statusText || "에이전트 연결 실패"}
          </p>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 transition-colors hover:text-gray-600"
          >
            <CloseIcon />
          </button>
        </div>
      </div>
    );
  }

  const isUploading = state === "uploading";
  const label = statusText ?? (isUploading ? "파일 분석 중..." : "일시정지됨");

  return (
    <div className="fixed right-8 top-20 z-50 w-[280px] rounded-xl bg-white p-5 shadow-lg">
      <div className="flex items-start justify-between">
        <p className="text-3xl font-bold text-gray-900">{progress}%</p>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onStop}
            className="rounded p-1 text-gray-400 transition-colors hover:text-gray-600"
          >
            <StopIcon />
          </button>
          <button
            type="button"
            onClick={isUploading ? onPause : onResume}
            className={cn(
              "rounded p-1 transition-colors",
              isUploading
                ? "text-gray-400 hover:text-gray-600"
                : "text-indigo-500 hover:text-indigo-600"
            )}
          >
            {isUploading ? <PauseIcon /> : <PlayIcon />}
          </button>
        </div>
      </div>

      <p className="mt-1 text-sm font-medium text-gray-900">{label}</p>

      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-gray-200">
        <div
          className="h-full rounded-full bg-indigo-500 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
