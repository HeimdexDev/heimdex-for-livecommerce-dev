"use client";

import { cn } from "@/lib/utils";

interface SyncSourceCardProps {
  title: string;
  onUpdate: () => void;
  isUploading?: boolean;
  disabled?: boolean;
}

export function SyncSourceCard({
  title,
  onUpdate,
  isUploading = false,
  disabled = false,
}: SyncSourceCardProps) {
  const isInteractive = !disabled && !isUploading;

  return (
    <div
      className={cn(
        "flex flex-col justify-between rounded-xl bg-white p-6 shadow-sm",
        disabled && "opacity-60",
      )}
    >
      <div>
        <div className="mb-6 flex items-center justify-between">
          <h3 className="text-lg font-bold text-gray-900">{title}</h3>
          {disabled && (
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
              준비 중
            </span>
          )}
        </div>

        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">최신 분석 시간</span>
            <span className="text-sm font-semibold text-gray-900">
              {disabled ? "—" : "2시간 전"}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">연결 상태</span>
            {disabled ? (
              <span className="rounded-full bg-gray-100 px-3 py-0.5 text-xs font-medium text-gray-400">
                미지원
              </span>
            ) : (
              <span className="rounded-full bg-red-50 px-3 py-0.5 text-xs font-medium text-red-500">
                연결 필요
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">상태</span>
            {disabled ? (
              <span className="rounded-full bg-gray-100 px-3 py-0.5 text-xs font-medium text-gray-400">
                —
              </span>
            ) : (
              <span className="rounded-full bg-red-50 px-3 py-0.5 text-xs font-medium text-red-500">
                오류 있음
              </span>
            )}
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={onUpdate}
        disabled={!isInteractive}
        className={cn(
          "mt-8 w-full rounded-lg py-3 text-sm font-medium transition-colors",
          isInteractive
            ? "bg-indigo-500 text-white hover:bg-indigo-600"
            : "cursor-not-allowed bg-gray-200 text-gray-400",
        )}
      >
        {disabled ? "준비 중" : `${title} 업데이트`}
      </button>
    </div>
  );
}
