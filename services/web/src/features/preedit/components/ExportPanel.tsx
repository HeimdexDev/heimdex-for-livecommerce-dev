"use client";

import { useState, useCallback } from "react";
import type { RenderJobResponse } from "@/lib/api/shorts-render";
import { getApiBaseUrl } from "@/lib/api/utils";

// Must stay in sync with the RenderStatus union in usePreeditExport.ts —
// `rate_limited` is distinct from `failed` so the UI can show a "wait a
// moment" message instead of a generic error.
type RenderStatus =
  | "idle"
  | "submitting"
  | "queued"
  | "rendering"
  | "completed"
  | "failed"
  | "rate_limited";

const DRIVE_PATH_KEY = "heimdex_drive_mount_path";

function readDrivePath(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(DRIVE_PATH_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeDrivePath(path: string): void {
  try {
    localStorage.setItem(DRIVE_PATH_KEY, path);
  } catch {
    /* localStorage unavailable */
  }
}

interface ExportPanelProps {
  hasFilledRows: boolean;
  renderStatus: RenderStatus;
  renderJob: RenderJobResponse | null;
  renderError: string | null;
  onSubmitRender: () => void;
  onExportPremiere: (driveMountPath: string) => void;
  premiereError: string | null;
  isExportingPremiere: boolean;
  onReset: () => void;
  getToken: () => Promise<string | null>;
}

function renderStatusLabel(status: RenderStatus): string {
  switch (status) {
    case "submitting":
      return "제출 중...";
    case "queued":
      return "대기 중...";
    case "rendering":
      return "렌더링 중...";
    case "completed":
      return "완료";
    case "failed":
      return "실패";
    case "rate_limited":
      return "요청 제한에 도달했습니다. 잠시 후 다시 시도하세요.";
    default:
      return "";
  }
}

export function ExportPanel({
  hasFilledRows,
  renderStatus,
  renderJob,
  renderError,
  onSubmitRender,
  onExportPremiere,
  premiereError,
  isExportingPremiere,
  onReset,
  getToken,
}: ExportPanelProps) {
  const [drivePath, setDrivePath] = useState(readDrivePath);

  const handleDrivePathChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const val = e.target.value;
      setDrivePath(val);
      writeDrivePath(val);
    },
    [],
  );

  const handlePremiere = useCallback(() => {
    if (drivePath.trim()) {
      onExportPremiere(drivePath.trim());
    }
  }, [drivePath, onExportPremiere]);

  const handleDownload = useCallback(async () => {
    if (!renderJob) return;
    try {
      const token = await getToken();
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(
        `${getApiBaseUrl()}/api/shorts/render/${renderJob.id}/download`,
        { headers },
      );
      if (!res.ok) throw new Error("다운로드에 실패했습니다");

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `preedit_${renderJob.id}.mp4`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Download error handled silently
    }
  }, [renderJob, getToken]);

  const isRenderBusy =
    renderStatus === "submitting" ||
    renderStatus === "queued" ||
    renderStatus === "rendering";

  return (
    <div className="flex flex-col gap-4">
      {/* Render section */}
      <div>
        <h3 className="text-xs font-semibold text-gray-600">렌더링</h3>
        <div className="mt-2">
          {renderStatus === "idle" && (
            <button
              type="button"
              disabled={!hasFilledRows}
              onClick={onSubmitRender}
              className="w-full rounded-lg bg-indigo-500 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-600 disabled:bg-gray-300 disabled:text-gray-500"
            >
              렌더링 시작
            </button>
          )}

          {isRenderBusy && (
            <div className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
              <span className="text-xs text-indigo-700">
                {renderStatusLabel(renderStatus)}
              </span>
            </div>
          )}

          {renderStatus === "completed" && (
            <div className="flex flex-col gap-2">
              <div className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs text-green-700">
                렌더링 완료
              </div>
              <button
                type="button"
                onClick={handleDownload}
                className="w-full rounded-lg bg-indigo-500 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-600"
              >
                다운로드
              </button>
              <button
                type="button"
                onClick={onReset}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                다시 시작
              </button>
            </div>
          )}

          {renderStatus === "failed" && (
            <div className="flex flex-col gap-2">
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
                {renderError || "렌더링에 실패했습니다"}
              </div>
              <button
                type="button"
                onClick={() => {
                  onReset();
                }}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                다시 시도
              </button>
            </div>
          )}

          {!hasFilledRows && renderStatus === "idle" && (
            <p className="mt-1 text-[10px] text-gray-400">
              행을 선택하세요
            </p>
          )}
        </div>
      </div>

      {/* Premiere section */}
      <div>
        <h3 className="text-xs font-semibold text-gray-600">Premiere Pro</h3>
        <div className="mt-2 flex flex-col gap-2">
          <div>
            <label className="text-[10px] text-gray-500">
              Google Drive 경로
            </label>
            <input
              type="text"
              value={drivePath}
              onChange={handleDrivePathChange}
              placeholder="/Users/.../Google Drive"
              className="mt-1 w-full rounded-md border border-gray-300 px-2 py-1.5 text-xs text-gray-700 outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-400"
            />
          </div>
          <button
            type="button"
            disabled={!hasFilledRows || !drivePath.trim() || isExportingPremiere}
            onClick={handlePremiere}
            className="w-full rounded-lg border border-gray-300 bg-white py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:bg-gray-100 disabled:text-gray-400"
          >
            {isExportingPremiere ? (
              <span className="inline-flex items-center gap-2">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-500 border-t-transparent" />
                다운로드 중...
              </span>
            ) : (
              "패키지 다운로드"
            )}
          </button>
          {premiereError && (
            <p className="text-[10px] text-red-500">{premiereError}</p>
          )}
        </div>
      </div>
    </div>
  );
}
