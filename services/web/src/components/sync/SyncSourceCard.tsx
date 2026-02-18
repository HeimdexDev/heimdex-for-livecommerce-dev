"use client";

import { cn } from "@/lib/utils";

export type ConnectionStatus = "connected" | "offline" | "unknown";
export type ProcessingStatus = "complete" | "processing" | "error" | "unknown";

interface SyncSourceCardProps {
  title: string;
  onUpdate: () => void;
  onCardClick?: () => void;
  isUploading?: boolean;
  disabled?: boolean;
  selected?: boolean;
  connectionStatus?: ConnectionStatus;
  processingStatus?: ProcessingStatus;
  lastAnalyzedAt?: string | null;
}

function formatRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const diff = Date.now() - new Date(dateStr).getTime();
  if (diff < 0) return "방금 전";
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "방금 전";
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
}

const CONNECTION_CONFIG: Record<
  ConnectionStatus,
  { label: string; className: string }
> = {
  connected: {
    label: "연결됨",
    className: "bg-emerald-50 text-emerald-600",
  },
  offline: {
    label: "오프라인",
    className: "bg-red-50 text-red-500",
  },
  unknown: {
    label: "확인 중",
    className: "bg-gray-100 text-gray-400",
  },
};

const PROCESSING_CONFIG: Record<
  ProcessingStatus,
  { label: string; className: string }
> = {
  complete: {
    label: "완료",
    className: "bg-emerald-50 text-emerald-600",
  },
  processing: {
    label: "처리 중",
    className: "bg-blue-50 text-blue-600",
  },
  error: {
    label: "오류 있음",
    className: "bg-red-50 text-red-500",
  },
  unknown: {
    label: "—",
    className: "bg-gray-100 text-gray-400",
  },
};

export function SyncSourceCard({
  title,
  onUpdate,
  onCardClick,
  isUploading = false,
  disabled = false,
  selected = false,
  connectionStatus = "unknown",
  processingStatus = "unknown",
  lastAnalyzedAt,
}: SyncSourceCardProps) {
  const isInteractive = !disabled && !isUploading;

  const connCfg = disabled
    ? { label: "미지원", className: "bg-gray-100 text-gray-400" }
    : CONNECTION_CONFIG[connectionStatus];

  const procCfg = disabled
    ? { label: "—", className: "bg-gray-100 text-gray-400" }
    : PROCESSING_CONFIG[processingStatus];

  return (
    <div
      onClick={!disabled ? onCardClick : undefined}
      className={cn(
        "flex flex-col justify-between rounded-xl bg-white p-6 shadow-sm transition-all",
        disabled && "opacity-60",
        !disabled && "cursor-pointer hover:shadow-md",
        selected && "ring-2 ring-indigo-500",
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
              {disabled ? "—" : formatRelativeTime(lastAnalyzedAt)}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">연결 상태</span>
            <span
              className={cn(
                "rounded-full px-3 py-0.5 text-xs font-medium",
                connCfg.className,
              )}
            >
              {connCfg.label}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">상태</span>
            <span
              className={cn(
                "rounded-full px-3 py-0.5 text-xs font-medium",
                procCfg.className,
              )}
            >
              {procCfg.label}
            </span>
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
