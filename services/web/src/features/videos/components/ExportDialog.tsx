"use client";

import { FormEvent, useEffect, useState } from "react";
import { pickDirectory } from "@/lib/agent";

const DEFAULT_OUTPUT_DIR = "~/Desktop/Heimdex Exports";
const FRAME_RATE_OPTIONS = [24, 25, 29.97, 30, 60];
const DRIVE_MOUNT_PATH_KEY = "heimdex_drive_mount_path";

interface ExportDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onExport: (config: {
    projectName: string;
    outputDir: string;
    frameRate: number;
    driveMountPath?: string;
  }) => void;
  selectedCount: number;
  isExporting: boolean;
  defaultProjectName: string;
  agentAvailable?: boolean;
  isCloudExport?: boolean;
}

export function ExportDialog({
  isOpen,
  onClose,
  onExport,
  selectedCount,
  isExporting,
  defaultProjectName,
  agentAvailable = false,
  isCloudExport = false,
}: ExportDialogProps) {
  const [projectName, setProjectName] = useState(defaultProjectName);
  const [outputDir, setOutputDir] = useState(DEFAULT_OUTPUT_DIR);
  const [frameRate, setFrameRate] = useState(29.97);
  const [isBrowsing, setIsBrowsing] = useState(false);
  const [driveMountPath, setDriveMountPath] = useState(() => {
    if (typeof window === "undefined") return "";
    return localStorage.getItem(DRIVE_MOUNT_PATH_KEY) ?? "";
  });

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) return;
    setProjectName(defaultProjectName);
  }, [defaultProjectName, isOpen]);

  if (!isOpen) {
    return null;
  }

  const isSubmitDisabled =
    isExporting || projectName.trim().length === 0 || (!isCloudExport && outputDir.trim().length === 0) || (isCloudExport && driveMountPath.trim().length === 0);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitDisabled) return;
    if (isCloudExport && driveMountPath.trim()) {
      localStorage.setItem(DRIVE_MOUNT_PATH_KEY, driveMountPath.trim());
    }
    onExport({
      projectName: projectName.trim(),
      outputDir: outputDir.trim(),
      frameRate,
      driveMountPath: isCloudExport ? driveMountPath.trim() : undefined,
    });
  };

  const handleBrowse = async () => {
    setIsBrowsing(true);
    try {
      const path = await pickDirectory();
      if (path) {
        setOutputDir(path);
      }
    } catch {
      // no-op: keep current value
    } finally {
      setIsBrowsing(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-label="Close export dialog"
      />
      <div className="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-md">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Premiere Pro 내보내기</h3>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="export-project-name" className="block text-sm font-medium text-gray-700 mb-1">
              프로젝트 이름
            </label>
            <input
              id="export-project-name"
              className="input-field"
              value={projectName}
              onChange={(event) => setProjectName(event.target.value)}
              required
            />
          </div>

          {isCloudExport ? (
            <div>
              <label htmlFor="export-drive-mount" className="block text-sm font-medium text-gray-700 mb-1">
                Google Drive 경로
              </label>
              <input
                id="export-drive-mount"
                className="input-field"
                value={driveMountPath}
                onChange={(event) => setDriveMountPath(event.target.value)}
                placeholder={typeof navigator !== "undefined" && navigator.platform?.includes("Win") ? "G:\\" : "/Volumes/GoogleDrive"}
                required
              />
              <p className="mt-1.5 text-xs text-gray-500">
                Google Drive for Desktop 마운트 경로를 입력하세요. Premiere Pro에서 영상 파일을 자동으로 연결합니다.
              </p>
            </div>
          ) : (
            <div>
              <label htmlFor="export-output-dir" className="block text-sm font-medium text-gray-700 mb-1">
                저장 위치
              </label>
              <div className="flex gap-2">
                <input
                  id="export-output-dir"
                  className="input-field flex-1 min-w-0"
                  value={outputDir}
                  onChange={(event) => setOutputDir(event.target.value)}
                  placeholder={DEFAULT_OUTPUT_DIR}
                  required
                />
                <button
                  type="button"
                  className="flex-shrink-0 inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={handleBrowse}
                  disabled={!agentAvailable || isBrowsing || isExporting}
                  title={agentAvailable ? "폴더 선택" : "에이전트 연결 시 사용 가능"}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
                  </svg>
                  {isBrowsing ? "선택 중..." : "찾아보기"}
                </button>
              </div>
              {!agentAvailable && (
                <p className="mt-1.5 text-xs text-amber-600">
                  Heimdex 에이전트를 연결하면 폴더 탐색기로 저장 위치를 선택할 수 있습니다.
                </p>
              )}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">포맷</label>
            <p className="text-sm text-gray-700">{isCloudExport ? "FCP XML (Premiere Pro)" : "EDL (CMX 3600)"}</p>
          </div>

          <div>
            <label htmlFor="export-frame-rate" className="block text-sm font-medium text-gray-700 mb-1">
              프레임 레이트
            </label>
            <select
              id="export-frame-rate"
              className="input-field"
              value={frameRate}
              onChange={(event) => setFrameRate(Number(event.target.value))}
            >
              {FRAME_RATE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">클립</label>
            <p className="text-sm text-gray-700">{selectedCount}개 선택됨</p>
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 border border-gray-200 rounded-lg hover:bg-gray-50"
              onClick={onClose}
              disabled={isExporting}
            >
              취소
            </button>
            <button
              type="submit"
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
              disabled={isSubmitDisabled}
            >
              {isExporting
                ? (isCloudExport ? "다운로드 중..." : "내보내는 중...")
                : (isCloudExport ? "다운로드" : "내보내기")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
