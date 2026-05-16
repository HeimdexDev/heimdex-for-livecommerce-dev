"use client";

// figma: 1713:271669  (cache: .figma-cache/1713-271669_phase5_editor-1.api.json)
// node-name: GNB · spec: h=80 padL/R=32 / 뒤로가기 라벨 fs=16 fw=500 → text-base font-medium text-grayscale-500
// 공통 GNB는 editor-2 (1713:274802) 와 동일 스펙.
import { useCallback } from "react";
import Link from "next/link";
import { Maximize2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RenderStatus } from "../hooks/useCompositionExport";
import type { RenderJobResponse } from "@/lib/api/shorts-render";
import { getApiBaseUrl } from "@/lib/api/utils";

interface EditorHeaderProps {
  videoTitle: string | null;
  title: string;
  onTitleChange: (title: string) => void;
  clipCount: number;
  totalDurationMs: number;
  isDirty: boolean;
  renderStatus: RenderStatus;
  renderJob: RenderJobResponse | null;
  renderError: string | null;
  onRender: () => void;
  onRenderReset: () => void;
  onToggleFullscreen?: () => void;
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

const STATUS_LABELS: Record<RenderStatus, string> = {
  idle: "렌더링",
  submitting: "제출 중...",
  queued: "대기 중...",
  rendering: "렌더링 중...",
  completed: "완료",
  failed: "실패",
  rate_limited: "요청 제한",
};

export function EditorHeader({
  videoTitle,
  title,
  onTitleChange,
  clipCount,
  totalDurationMs,
  isDirty,
  renderStatus,
  renderJob,
  renderError,
  onRender,
  onRenderReset,
  onToggleFullscreen,
}: EditorHeaderProps) {
  const isWorking = renderStatus === "submitting" || renderStatus === "queued" || renderStatus === "rendering";
  const canRender = clipCount > 0 && !isWorking && renderStatus !== "completed";

  const handleBack = useCallback(
    (e: React.MouseEvent) => {
      if (isDirty && !window.confirm("저장하지 않은 변경사항이 있습니다. 나가시겠습니까?")) {
        e.preventDefault();
      }
    },
    [isDirty],
  );

  const handleDownload = useCallback(async () => {
    if (!renderJob?.download_url) return;
    // ``download_url`` is now an absolute presigned S3 URL (post
    // 2026-05-06 fix). The browser can hit it directly with no
    // auth header. Don't prefix the api base url — that would
    // produce a malformed double-host URL.
    const a = document.createElement("a");
    a.href = renderJob.download_url;
    a.download = `short_${renderJob.id}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, [renderJob]);

  return (
    <div className="flex h-20 items-center justify-between border-b border-grayscale-100 bg-white px-8">
      {/* Left: back + metadata */}
      <div className="flex items-center gap-3">
        <Link
          href="/export/shorts"
          onClick={handleBack}
          className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-base font-medium text-grayscale-500 hover:bg-grayscale-10 hover:text-grayscale-800"
        >
          <BackArrowIcon />
          <span>뒤로가기</span>
        </Link>

        <input
          type="text"
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          placeholder={videoTitle ?? "제목 없음"}
          className="max-w-64 truncate rounded-md border border-transparent px-2 py-1 text-[18px] font-semibold leading-[1.4] tracking-[-0.45px] text-grayscale-800 placeholder-grayscale-300 hover:border-grayscale-100 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
        />

        <span className="text-xs font-medium text-grayscale-500">
          {clipCount}개 장면 &middot; {Math.round(totalDurationMs / 1000)}초
          {isDirty && <span className="ml-1 text-amber-h-500">*</span>}
        </span>
      </div>

      {/* Right: render controls */}
      <div className="flex items-center gap-2">
        {onToggleFullscreen && (
          <button
            type="button"
            onClick={onToggleFullscreen}
            aria-label="전체보기"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-grayscale-500 transition-colors hover:bg-grayscale-100 hover:text-heimdex-navy-500"
          >
            <Maximize2 className="h-4 w-4" />
          </button>
        )}

        {/* Error message */}
        {renderError && (
          <span className="text-xs text-red-h-500 max-w-48 truncate">{renderError}</span>
        )}

        {/* Completed: download + new render */}
        {renderStatus === "completed" && renderJob && (
          <>
            <button
              type="button"
              onClick={handleDownload}
              className="inline-flex items-center gap-1.5 rounded-lg bg-heimdex-navy-500 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
            >
              <DownloadIcon />
              다운로드
            </button>
            <button
              type="button"
              onClick={onRenderReset}
              className="rounded-lg border border-grayscale-200 bg-white px-3 py-2 text-sm font-semibold text-grayscale-800 transition-colors hover:bg-grayscale-10"
            >
              다시 렌더링
            </button>
          </>
        )}

        {/* Failed: retry */}
        {renderStatus === "failed" && (
          <button
            type="button"
            onClick={onRenderReset}
            className="rounded-lg border border-grayscale-200 bg-white px-3 py-2 text-sm font-semibold text-grayscale-800 transition-colors hover:bg-grayscale-10"
          >
            재시도
          </button>
        )}

        {/* Render button */}
        {renderStatus !== "completed" && (
          <button
            type="button"
            onClick={onRender}
            disabled={!canRender}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors",
              canRender
                ? "bg-heimdex-navy-500 text-white hover:bg-heimdex-navy-600"
                : "cursor-not-allowed bg-grayscale-100 text-grayscale-400",
            )}
          >
            {isWorking && (
              <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
            )}
            {STATUS_LABELS[renderStatus]}
          </button>
        )}
      </div>
    </div>
  );
}
