"use client";

// figma: 1602:37719 (editor GNB)
// spec: h=80 px=32 / back ▸ chevron-left + "뒤로가기" 16px medium grayscale-500
//        title 18px semibold black + "N개 장면" 12px medium neutral-h-500
//        right ▸ [템플릿 저장 slot] [내보내기 primary] / h=32 px=10 py=6 r=8 fs=12
import type { ReactNode } from "react";
import { useCallback } from "react";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import type { RenderStatus } from "../hooks/useCompositionExport";
import type { RenderJobResponse } from "@/lib/api/shorts-render";

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
  // Slot rendered between metadata and the export button — the page wires
  // a TemplateSaveMenu in here so the GNB ordering stays figma-aligned
  // (back / title / scenes / 템플릿 저장 / 내보내기).
  templateSaveSlot?: ReactNode;
}

function DownloadIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

const STATUS_LABELS: Record<RenderStatus, string> = {
  idle: "내보내기",
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
  templateSaveSlot,
}: EditorHeaderProps) {
  void totalDurationMs;
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
    const a = document.createElement("a");
    a.href = renderJob.download_url;
    a.download = `short_${renderJob.id}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }, [renderJob]);

  return (
    <div className="flex h-20 items-center border-b border-grayscale-100 bg-white px-8">
      {/* Left: back + metadata — figma gap=20 */}
      <div className="flex items-center gap-5">
        <Link
          href="/export/shorts"
          onClick={handleBack}
          className="inline-flex items-center gap-1 text-grayscale-500 hover:text-grayscale-800"
        >
          <ChevronLeft className="h-6 w-6" strokeWidth={2} />
          <span className="text-[16px] font-medium leading-[1.4] tracking-[-0.4px]">
            뒤로가기
          </span>
        </Link>

        <div className="flex items-center gap-[10px]">
          <input
            type="text"
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder={videoTitle ?? "제목 없음"}
            aria-label="영상 제목"
            className="max-w-64 truncate rounded-md border border-transparent px-1 text-[18px] font-semibold leading-[1.4] tracking-[-0.45px] text-black placeholder-grayscale-300 hover:border-grayscale-100 focus:border-heimdex-navy-500 focus:outline-none focus:ring-1 focus:ring-heimdex-navy-500"
          />
          <span className="whitespace-nowrap text-[12px] font-medium leading-[1.4] tracking-[-0.3px] text-neutral-h-500">
            {clipCount}개 장면
            {isDirty && <span className="ml-1 text-amber-h-500">*</span>}
          </span>
        </div>
      </div>

      {/* Right: 템플릿 저장 + 내보내기 — figma h=32 px=10 py=6 r=8 fs=12 */}
      <div className="ml-auto flex items-center gap-2">
        {renderError && (
          <span className="max-w-48 truncate text-xs text-red-h-500">{renderError}</span>
        )}

        {templateSaveSlot}

        {renderStatus === "completed" && renderJob && (
          <>
            <button
              type="button"
              onClick={handleDownload}
              className="inline-flex h-8 items-center gap-1.5 rounded-[8px] bg-heimdex-navy-500 px-[10px] py-[6px] text-[12px] font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
            >
              <DownloadIcon />
              다운로드
            </button>
            <button
              type="button"
              onClick={onRenderReset}
              className="h-8 rounded-[8px] border border-neutral-h-500 bg-white px-[10px] py-[6px] text-[12px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10"
            >
              다시 렌더링
            </button>
          </>
        )}

        {renderStatus === "failed" && (
          <button
            type="button"
            onClick={onRenderReset}
            className="h-8 rounded-[8px] border border-neutral-h-500 bg-white px-[10px] py-[6px] text-[12px] font-semibold text-neutral-h-500 transition-colors hover:bg-grayscale-10"
          >
            재시도
          </button>
        )}

        {renderStatus !== "completed" && (
          <button
            type="button"
            onClick={onRender}
            disabled={!canRender}
            className={cn(
              "inline-flex h-8 items-center gap-2 rounded-[8px] px-[10px] py-[6px] text-[12px] font-semibold leading-none transition-colors",
              canRender
                ? "bg-heimdex-navy-500 text-white hover:bg-heimdex-navy-600"
                : "cursor-not-allowed bg-neutral-h-100 text-neutral-h-300",
            )}
          >
            {isWorking && (
              <div className="h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
            )}
            {STATUS_LABELS[renderStatus]}
          </button>
        )}
      </div>
    </div>
  );
}
