"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  exportPremierePackage,
  initiateProxyPack,
  pollProxyPackStatus,
  type ProxyPackStatusResponse,
} from "@/lib/cloud-export";
import { useSceneBasket, type BasketItem } from "./useSceneBasket";

const STORAGE_KEY = "heimdex_drive_mount_path";
const CUSTOM_OPTION = "__custom__";
const POLL_INTERVAL_MS = 3000;

type ExportTab = "fcpxml" | "proxy-pack";

const fmtBytes = (b: number): string => {
  if (b >= 1_073_741_824) return `${(b / 1_073_741_824).toFixed(1)} GB`;
  if (b >= 1_048_576) return `${(b / 1_048_576).toFixed(1)} MB`;
  return `${(b / 1024).toFixed(0)} KB`;
};

interface ExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** When provided, export these items instead of the scene basket. */
  overrideItems?: BasketItem[];
}

export function ExportModal({ isOpen, onClose, overrideItems }: ExportModalProps) {
  const basket = useSceneBasket();
  const items = overrideItems ?? basket.items;
  const { getAccessToken } = useAuth();

  // --- Shared state ---
  const [activeTab, setActiveTab] = useState<ExportTab>("proxy-pack");
  const [sequenceName, setSequenceName] = useState("Heimdex Export");
  const [clipGapMs, setClipGapMs] = useState(0);
  const [includeMarkers, setIncludeMarkers] = useState(true);
  const [includeTranscriptMarkers, setIncludeTranscriptMarkers] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // --- FCPXML tab state ---
  const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.userAgent);
  const driveOptions = useMemo(
    () =>
      isMac
        ? ["~/Library/CloudStorage/GoogleDrive-email@gmail.com/", "/Volumes/GoogleDrive"]
        : ["G:\\My Drive\\"],
    [isMac]
  );
  const [selectedDriveOption, setSelectedDriveOption] = useState(driveOptions[0]);
  const [customDrivePath, setCustomDrivePath] = useState("");
  const [drivePath, setDrivePath] = useState(driveOptions[0]);

  // --- Proxy Pack tab state ---
  const [proxyJobId, setProxyJobId] = useState<string | null>(null);
  const [proxyStatus, setProxyStatus] = useState<ProxyPackStatusResponse | null>(null);
  const [proxyEstimatedBytes, setProxyEstimatedBytes] = useState<number | null>(null);
  const [proxyPolling, setProxyPolling] = useState(false);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // --- Drive path persistence ---
  useEffect(() => {
    const defaultPath = driveOptions[0];
    setSelectedDriveOption(defaultPath);
    setDrivePath(defaultPath);

    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) return;

    if (driveOptions.includes(saved)) {
      setSelectedDriveOption(saved);
      setDrivePath(saved);
      return;
    }

    setSelectedDriveOption(CUSTOM_OPTION);
    setCustomDrivePath(saved);
    setDrivePath(saved);
  }, [driveOptions]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, drivePath);
  }, [drivePath]);

  // --- Cleanup polling on unmount or modal close ---
  useEffect(() => {
    if (!isOpen) {
      stopPolling();
    }
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  const stopPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    setProxyPolling(false);
  };

  // --- Tab switching ---
  const handleTabSwitch = (tab: ExportTab) => {
    setActiveTab(tab);
    setError("");
    setSuccess("");
  };

  // --- FCPXML Export handler (existing logic) ---
  const handleFcpxmlExport = async () => {
    if (!drivePath.trim()) {
      setError("Google 드라이브 위치를 입력해주세요.");
      return;
    }
    if (items.length === 0) {
      setError("내보낼 장면이 없습니다.");
      return;
    }

    setLoading(true);
    setError("");
    setSuccess("");
    try {
      await exportPremierePackage(
        {
          sequence_name: sequenceName,
          drive_mount_path: drivePath,
          clips: items.map((item) => ({
            scene_id: item.scene_id,
            video_id: item.video_id,
            video_title: item.video_title,
            start_ms: item.start_ms,
            end_ms: item.end_ms,
            label: item.label,
            keyword_tags: item.keyword_tags ?? [],
            transcript_raw: item.transcript_raw ?? "",
          })),
          clip_gap_ms: clipGapMs,
          include_markers: includeMarkers,
          include_transcript_markers: includeTranscriptMarkers,
        },
        getAccessToken
      );
      setSuccess("내보내기가 완료되었습니다. 다운로드를 확인해주세요.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "내보내기에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  // --- Proxy Pack Export handler ---
  const handleProxyPackExport = async () => {
    if (items.length === 0) {
      setError("내보낼 장면이 없습니다.");
      return;
    }

    setLoading(true);
    setError("");
    setSuccess("");
    setProxyJobId(null);
    setProxyStatus(null);
    setProxyEstimatedBytes(null);

    try {
      const initResponse = await initiateProxyPack(
        {
          sequence_name: sequenceName,
          clips: items.map((item) => ({
            scene_id: item.scene_id,
            video_id: item.video_id,
            video_title: item.video_title,
            start_ms: item.start_ms,
            end_ms: item.end_ms,
            label: item.label,
            keyword_tags: item.keyword_tags ?? [],
            transcript_raw: item.transcript_raw ?? "",
          })),
          clip_gap_ms: clipGapMs,
          include_markers: includeMarkers,
          include_transcript_markers: includeTranscriptMarkers,
        },
        getAccessToken
      );

      setProxyJobId(initResponse.job_id);
      setProxyEstimatedBytes(initResponse.estimated_size_bytes);

      // Cached hit — already ready
      if (initResponse.status === "ready") {
        const statusRes = await pollProxyPackStatus(initResponse.job_id, getAccessToken);
        setProxyStatus(statusRes);
        setSuccess("캐시된 내보내기를 찾았습니다. 바로 다운로드할 수 있습니다.");
        setLoading(false);
        return;
      }

      // Start polling
      setProxyPolling(true);
      setLoading(false);
      startPolling(initResponse.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "프록시 팩 생성에 실패했습니다.");
      setLoading(false);
    }
  };

  const startPolling = (jobId: string) => {
    stopPolling();
    setProxyPolling(true);

    pollTimerRef.current = setInterval(async () => {
      try {
        const statusRes = await pollProxyPackStatus(jobId, getAccessToken);
        setProxyStatus(statusRes);

        const terminal = ["ready", "failed", "expired"];
        if (terminal.includes(statusRes.status)) {
          stopPolling();
          if (statusRes.status === "ready") {
            setSuccess("프록시 팩이 준비되었습니다. 다운로드 버튼을 클릭하세요.");
          } else if (statusRes.status === "failed") {
            setError(statusRes.error ?? "내보내기에 실패했습니다.");
          } else if (statusRes.status === "expired") {
            setError("내보내기가 만료되었습니다. 다시 시도해주세요.");
          }
        }
      } catch (e) {
        stopPolling();
        setError(e instanceof Error ? e.message : "상태 확인에 실패했습니다.");
      }
    }, POLL_INTERVAL_MS);
  };

  const handleDownload = () => {
    if (proxyStatus?.download_url) {
      window.open(proxyStatus.download_url, "_blank");
    }
  };

  if (!isOpen) return null;

  const isProxyInProgress = proxyPolling || (proxyStatus && !["ready", "failed", "expired"].includes(proxyStatus.status));
  const isProxyReady = proxyStatus?.status === "ready" && proxyStatus.download_url;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        onClick={onClose}
        aria-label="모달 닫기"
      />

      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4 p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Premiere 내보내기</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 text-xl leading-none"
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        {/* Tab selector — hidden while FCPXML tab is disabled for customers */}
        {false && (
        <div className="bg-gray-50 p-1 rounded-xl flex gap-2 mb-4">
          <button
            type="button"
            onClick={() => handleTabSwitch("fcpxml")}
            className={`flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === "fcpxml"
                ? "bg-primary-600 text-white"
                : "bg-transparent text-gray-700 hover:bg-gray-200"
            }`}
          >
            FCPXML + Google 드라이브
          </button>
          <button
            type="button"
            onClick={() => handleTabSwitch("proxy-pack")}
            className={`flex-1 px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
              activeTab === "proxy-pack"
                ? "bg-primary-600 text-white"
                : "bg-transparent text-gray-700 hover:bg-gray-200"
            }`}
          >
            프록시 팩
          </button>
        </div>
        )}

        <div className="space-y-4">
          {/* Proxy Pack info banner */}
          {activeTab === "proxy-pack" && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2">
              <p className="text-xs text-blue-700">
                프록시 영상이 포함된 ZIP 파일을 생성합니다. Google 드라이브 설치 없이 바로 Premiere Pro에서 열 수 있습니다.
              </p>
            </div>
          )}

          {/* Sequence name (shared) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">시퀀스 이름</label>
            <input
              type="text"
              value={sequenceName}
              onChange={(e) => setSequenceName(e.target.value)}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
              placeholder="Heimdex Export"
            />
          </div>

          {/* Drive mount path (FCPXML tab only) */}
          {activeTab === "fcpxml" && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Google 드라이브 위치</label>
              <select
                value={selectedDriveOption}
                onChange={(e) => {
                  const value = e.target.value;
                  setSelectedDriveOption(value);
                  if (value === CUSTOM_OPTION) {
                    setDrivePath(customDrivePath);
                  } else {
                    setDrivePath(value);
                  }
                }}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
              >
                {driveOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
                <option value={CUSTOM_OPTION}>직접 입력...</option>
              </select>
              {selectedDriveOption === CUSTOM_OPTION && (
                <input
                  type="text"
                  value={customDrivePath}
                  onChange={(e) => {
                    const value = e.target.value;
                    setCustomDrivePath(value);
                    setDrivePath(value);
                  }}
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none mt-2"
                  placeholder="경로를 입력하세요"
                />
              )}
              <p className="text-xs text-gray-400 mt-1">
                이 경로는 Premiere Pro에서 원본 미디어를 찾는 데 사용됩니다.
              </p>
            </div>
          )}

          {/* Clip gap (shared) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">클립 간격</label>
            <select
              value={clipGapMs}
              onChange={(e) => setClipGapMs(Number(e.target.value))}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-primary-500 focus:ring-1 focus:ring-primary-500 outline-none"
            >
              <option value={0}>없음</option>
              <option value={1000}>1초</option>
            </select>
          </div>

          {/* Markers (shared) */}
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeMarkers}
              onChange={(e) => setIncludeMarkers(e.target.checked)}
            />
            마커 포함
          </label>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={includeTranscriptMarkers}
              onChange={(e) => setIncludeTranscriptMarkers(e.target.checked)}
            />
            자막 마커 포함
          </label>

          {/* Proxy Pack: polling status UI */}
          {activeTab === "proxy-pack" && proxyJobId && (
            <div className="border border-gray-200 rounded-lg p-3 space-y-2">
              {/* Estimated size */}
              {proxyEstimatedBytes != null && (
                <p className="text-xs text-gray-500">
                  예상 크기: {fmtBytes(proxyEstimatedBytes)}
                </p>
              )}

              {/* In-progress states */}
              {isProxyInProgress && (
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 animate-spin text-primary-600" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  <span className="text-sm text-gray-600">
                    {proxyStatus?.status === "uploading" ? "업로드 중..." : "내보내기 준비 중..."}
                  </span>
                </div>
              )}

              {/* Ready: download button */}
              {isProxyReady && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-green-600">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    <span className="text-sm font-medium">준비 완료</span>
                    {proxyStatus.size_bytes != null && (
                      <span className="text-xs text-gray-500">({fmtBytes(proxyStatus.size_bytes)})</span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={handleDownload}
                    className="w-full bg-green-600 text-white py-2 rounded-lg hover:bg-green-700 text-sm font-medium flex items-center justify-center gap-2"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    프록시 팩 다운로드 (.zip)
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Error / Success messages */}
          {error && <p className="text-sm text-red-600">{error}</p>}
          {success && <p className="text-sm text-green-600">{success}</p>}

          {/* Primary action button */}
          {activeTab === "fcpxml" && (
            <button
              type="button"
              onClick={handleFcpxmlExport}
              disabled={loading}
              className="w-full bg-primary-600 text-white py-2.5 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {loading && (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                </svg>
              )}
              Premiere 내보내기 패키지 다운로드 (.zip)
            </button>
          )}

          {activeTab === "proxy-pack" && !proxyJobId && (
            <button
              type="button"
              onClick={handleProxyPackExport}
              disabled={loading}
              className="w-full bg-primary-600 text-white py-2.5 rounded-lg hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {loading && (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                </svg>
              )}
              프록시 팩 생성 시작
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
