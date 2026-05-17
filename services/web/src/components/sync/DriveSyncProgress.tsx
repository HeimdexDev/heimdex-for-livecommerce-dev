"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { DriveSyncProgress as DriveSyncProgressData } from "@/lib/types";

interface Props {
  progress: DriveSyncProgressData | null;
  loading?: boolean;
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "방금 전";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분 전`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
}

function processingStatusLabel(status: string): string {
  if (status.includes("download")) return "다운로드 중";
  if (status.includes("transcode") || status.includes("convert")) return "변환 중";
  return "분석 중";
}

export function DriveSyncProgress({ progress, loading }: Props) {
  const [recentExpanded, setRecentExpanded] = useState(false);

  if (loading && !progress) {
    return (
      <div className="mt-4 rounded-xl border border-gray-100 bg-white p-5">
        <div className="space-y-3">
          <div className="h-3 w-1/3 animate-pulse rounded-full bg-gray-100" />
          <div className="h-2.5 w-full animate-pulse rounded-full bg-gray-100" />
          <div className="h-2.5 w-2/3 animate-pulse rounded-full bg-gray-100" />
        </div>
      </div>
    );
  }

  if (!progress) return null;

  const { total_files, indexed, processing, pending, failed, percent_complete, current_file, recent_completed, failed_files, enrichment } = progress;

  const isComplete = percent_complete >= 100 && failed === 0 && total_files > 0;
  const hasEnrichment =
    enrichment.stt_done + enrichment.stt_pending + enrichment.stt_running +
    enrichment.ocr_done + enrichment.ocr_pending + enrichment.ocr_running +
    enrichment.caption_done + enrichment.caption_pending + enrichment.caption_running > 0;

  const enrichmentItems = [
    {
      label: "STT",
      done: enrichment.stt_done,
      total: enrichment.stt_done + enrichment.stt_pending + enrichment.stt_running,
      running: enrichment.stt_running > 0,
    },
    {
      label: "OCR",
      done: enrichment.ocr_done,
      total: enrichment.ocr_done + enrichment.ocr_pending + enrichment.ocr_running,
      running: enrichment.ocr_running > 0,
    },
    {
      label: "Caption",
      done: enrichment.caption_done,
      total: enrichment.caption_done + enrichment.caption_pending + enrichment.caption_running,
      running: enrichment.caption_running > 0,
    },
  ];

  return (
    <div className="mt-4 space-y-3 rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          {isComplete ? (
            <div className="flex items-center gap-1.5 text-sm font-medium text-green-600">
              <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
              모든 파일 동기화 완료
            </div>
          ) : total_files === 0 ? (
            <span className="text-sm text-gray-400">동기화할 파일이 없습니다</span>
          ) : (
            <span className="text-sm font-medium text-gray-700">
              {indexed}/{total_files} 완료
            </span>
          )}
          {total_files > 0 && (
            <span className="text-xs font-medium text-gray-400">{percent_complete}%</span>
          )}
        </div>

        {total_files > 0 && (
          <div className="relative h-2 w-full overflow-hidden rounded-full bg-gray-100">
            <div
              className={cn(
                "absolute left-0 top-0 h-full rounded-full transition-all duration-500",
                isComplete ? "bg-green-500" : "bg-blue-500",
              )}
              style={{ width: `${Math.max(0, Math.min(100, (indexed / total_files) * 100))}%` }}
            />
            {processing > 0 && (
              <div
                className="absolute top-0 h-full animate-pulse rounded-full bg-blue-300/60"
                style={{
                  left: `${(indexed / total_files) * 100}%`,
                  width: `${(processing / total_files) * 100}%`,
                }}
              />
            )}
          </div>
        )}
      </div>

      {current_file && (
        <div className="flex items-start gap-3 rounded-lg border border-blue-100 bg-blue-50/60 px-3.5 py-3">
          <span className="mt-0.5 inline-flex h-2 w-2 shrink-0 animate-pulse rounded-full bg-blue-500" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-blue-600">현재 처리 중</span>
              <span className="rounded-md bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-700">
                {processingStatusLabel(current_file.processing_status)}
              </span>
            </div>
            <p className="mt-0.5 truncate text-sm text-gray-700">{current_file.file_name}</p>
            {current_file.file_size_bytes !== null && (
              <p className="mt-0.5 text-xs text-gray-400">{formatFileSize(current_file.file_size_bytes)}</p>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-500">
          <span className="h-1.5 w-1.5 rounded-full bg-gray-400" />
          {pending} 대기
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-600">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-500" />
          {processing} 처리 중
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-1 text-xs font-medium text-green-600">
          <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
          {indexed} 완료
        </span>
        {failed > 0 && (
          <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2.5 py-1 text-xs font-medium text-red-600">
            <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
            {failed} 실패
          </span>
        )}
      </div>

      {hasEnrichment && (
        <div className="rounded-lg border border-gray-100 bg-gray-50 px-3.5 py-3">
          <p className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-gray-400">AI 분석</p>
          <div className="flex flex-wrap gap-3">
            {enrichmentItems.map(({ label, done, total, running }) => {
              if (total === 0) return null;
              const allDone = done === total;
              return (
                <div key={label} className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      allDone ? "bg-green-500" : running ? "animate-pulse bg-blue-500" : "bg-gray-300",
                    )}
                  />
                  <span className="text-xs text-gray-500">{label}</span>
                  <span
                    className={cn(
                      "text-xs font-medium",
                      allDone ? "text-green-600" : running ? "text-blue-600" : "text-gray-400",
                    )}
                  >
                    {done}/{total}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {failed_files.length > 0 && (
        <div className="rounded-lg border border-red-100 bg-red-50/70 px-3.5 py-3">
          <p className="mb-2 text-xs font-semibold text-red-600">실패한 파일</p>
          <div className="space-y-2">
            {failed_files.map((f) => (
              <div key={f.id} className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium text-gray-700">{f.file_name}</p>
                  {f.last_error && (
                    <p className="mt-0.5 truncate text-xs text-red-500">{f.last_error}</p>
                  )}
                </div>
                <span className="shrink-0 rounded-md bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-600">
                  재시도 {f.retry_count}/3
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {recent_completed.length > 0 && (
        <div>
          <button
            onClick={() => setRecentExpanded((prev) => !prev)}
            className="flex w-full items-center justify-between rounded-lg px-1 py-1 text-left hover:bg-gray-50"
          >
            <span className="text-xs font-medium text-gray-500">최근 완료 ({recent_completed.length})</span>
            <svg
              className={cn(
                "h-3.5 w-3.5 text-gray-400 transition-transform duration-200",
                recentExpanded && "rotate-180",
              )}
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>

          {recentExpanded && (
            <div className="mt-1.5 space-y-1.5">
              {recent_completed.map((f, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between gap-2 rounded-lg bg-gray-50 px-3 py-2"
                >
                  <p className="min-w-0 truncate text-xs text-gray-700">{f.file_name}</p>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-xs text-gray-400">{f.scene_count}개 장면</span>
                    <span className="text-xs text-gray-300">·</span>
                    <span className="text-xs text-gray-400">{formatRelativeTime(f.completed_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
