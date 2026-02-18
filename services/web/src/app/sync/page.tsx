"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@/lib/auth";
import { getDevices } from "@/lib/api/devices";
import { getAgentStatus, pickFolder } from "@/lib/agent";
import type { AgentState } from "@/lib/agent";
import { AuthGuard } from "@/components/AuthGuard";
import { SyncSourceCard } from "@/components/sync/SyncSourceCard";
import type { ConnectionStatus, ProcessingStatus } from "@/components/sync/SyncSourceCard";
import { UploadProgress } from "@/components/sync/UploadProgress";
import { StopConfirmDialog } from "@/components/sync/StopConfirmDialog";
import type { DeviceListItem } from "@/lib/types";

type UploadState = "hidden" | "uploading" | "paused" | "complete" | "error";

const POLL_INTERVAL_MS = 2000;
const DEVICE_POLL_INTERVAL_MS = 30_000;
const MAX_UNREACHABLE_COUNT = 5;
const AGENT_STALE_MINUTES = 5;

const SYNC_SOURCES = [
  { title: "클라우드", disabled: true },
  { title: "외장하드", disabled: true },
  { title: "로컬 파일", disabled: false },
  { title: "수동 파일", disabled: true },
] as const;

function deriveConnectionStatus(devices: DeviceListItem[]): ConnectionStatus {
  const now = Date.now();
  const thresholdMs = AGENT_STALE_MINUTES * 60 * 1000;
  const hasConnected = devices.some(
    (d) =>
      !d.is_revoked &&
      d.last_seen_at !== null &&
      now - new Date(d.last_seen_at).getTime() < thresholdMs,
  );
  return hasConnected ? "connected" : "offline";
}

function deriveLastSeenAt(devices: DeviceListItem[]): string | null {
  const active = devices.filter((d) => !d.is_revoked && d.last_seen_at);
  if (active.length === 0) return null;
  return active.reduce((latest, d) =>
    new Date(d.last_seen_at!).getTime() > new Date(latest.last_seen_at!).getTime() ? d : latest,
  ).last_seen_at;
}

function deriveProcessingStatus(agentState: AgentState | null): ProcessingStatus {
  if (agentState === null) return "unknown";
  switch (agentState) {
    case "idle":
      return "complete";
    case "indexing":
      return "processing";
    case "error":
      return "error";
    case "paused":
      return "processing";
    default:
      return "unknown";
  }
}

function mapAgentState(agentState: AgentState): UploadState {
  switch (agentState) {
    case "indexing":
      return "uploading";
    case "paused":
      return "paused";
    case "error":
      return "error";
    case "idle":
      return "complete";
    default:
      return "uploading";
  }
}

function SyncContent() {
  const { getAccessToken } = useAuth();
  const [uploadState, setUploadState] = useState<UploadState>("hidden");
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState<string | undefined>();
  const [showStopDialog, setShowStopDialog] = useState(false);
  const [devices, setDevices] = useState<DeviceListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("unknown");
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus>("unknown");
  const [lastSeenAt, setLastSeenAt] = useState<string | null>(null);
  const pollingRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const unreachableCountRef = useRef(0);

  // Poll devices for connection status (same pattern as TopHeader)
  const loadDevices = useCallback(async () => {
    try {
      const res = await getDevices(getAccessToken);
      const active = res.devices.filter((d) => !d.is_revoked);
      setDevices(active);
      setConnectionStatus(deriveConnectionStatus(active));
      setLastSeenAt(deriveLastSeenAt(active));
    } catch {
      setDevices([]);
      setConnectionStatus("unknown");
    }
  }, [getAccessToken]);

  useEffect(() => {
    loadDevices();
    const id = setInterval(loadDevices, DEVICE_POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadDevices]);

  // Poll agent local status for processing state
  useEffect(() => {
    let mounted = true;
    async function pollProcessing() {
      const status = await getAgentStatus();
      if (!mounted) return;
      setProcessingStatus(deriveProcessingStatus(status?.state ?? null));
    }
    pollProcessing();
    const id = setInterval(pollProcessing, DEVICE_POLL_INTERVAL_MS);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  const stopPolling = useCallback(() => {
    pollingRef.current = false;
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const pollAgentStatus = useCallback(async () => {
    if (!pollingRef.current) return;

    const status = await getAgentStatus();

    if (!pollingRef.current) return;

    if (!status) {
      unreachableCountRef.current++;
      if (unreachableCountRef.current >= MAX_UNREACHABLE_COUNT) {
        stopPolling();
        setStatusText("에이전트 연결 실패");
        setUploadState("error");
      }
      return;
    }

    unreachableCountRef.current = 0;

    const mapped = mapAgentState(status.state);

    if (status.active_job) {
      setProgress(status.active_job.progress);
    }

    if (status.state === "error" && status.last_error) {
      setStatusText(status.last_error);
    } else {
      setStatusText(undefined);
    }

    if (mapped === "complete" || mapped === "error") {
      stopPolling();
      if (mapped === "complete") {
        setProgress(100);
      }
    }

    setUploadState(mapped);
  }, [stopPolling]);

  const startPolling = useCallback(() => {
    pollingRef.current = true;
    unreachableCountRef.current = 0;
    pollAgentStatus();
    intervalRef.current = setInterval(pollAgentStatus, POLL_INTERVAL_MS);
  }, [pollAgentStatus]);

  useEffect(() => stopPolling, [stopPolling]);

  const handleStartUpload = useCallback(async () => {
    if (uploadState !== "hidden") return;
    setError(null);

    try {
      setProgress(0);
      setStatusText("폴더 선택 중...");
      setUploadState("uploading");

      const result = await pickFolder();

      if (!result) {
        setUploadState("hidden");
        setStatusText(undefined);
        return;
      }

      setStatusText(undefined);
      startPolling();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "폴더 추가에 실패했습니다.";
      setError(message);
      setUploadState("hidden");
      setStatusText(undefined);
    }
  }, [uploadState, startPolling]);

  const handlePause = useCallback(() => setUploadState("paused"), []);
  const handleResume = useCallback(() => setUploadState("uploading"), []);

  const handleStopRequest = useCallback(() => setShowStopDialog(true), []);
  const handleStopCancel = useCallback(() => setShowStopDialog(false), []);
  const handleStopConfirm = useCallback(() => {
    stopPolling();
    setUploadState("hidden");
    setProgress(0);
    setStatusText(undefined);
    setShowStopDialog(false);
  }, [stopPolling]);

  const handleCloseComplete = useCallback(() => {
    setUploadState("hidden");
    setProgress(0);
    setStatusText(undefined);
  }, []);

  const isUploading = uploadState !== "hidden" && uploadState !== "complete" && uploadState !== "error";

  return (
    <div className="mx-auto max-w-5xl pt-12">
      <div className="mb-12 text-center">
        <h1 className="text-2xl font-bold text-gray-900">
          파일 추가 방식을 선택해 주세요.
        </h1>
        <p className="mt-3 text-gray-500">
          영상이 위치해있는 곳들을 선택하여 업데이트 할 수 있습니다.
        </p>
      </div>

      {error && (
        <div className="mx-auto mb-6 max-w-2xl rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {SYNC_SOURCES.map((source) => (
          <SyncSourceCard
            key={source.title}
            title={source.title}
            onUpdate={handleStartUpload}
            isUploading={isUploading}
            disabled={source.disabled}
            {...(!source.disabled && {
              connectionStatus,
              processingStatus,
              lastAnalyzedAt: lastSeenAt,
            })}
          />
        ))}
      </div>

      <UploadProgress
        state={uploadState}
        progress={progress}
        statusText={statusText}
        onStop={handleStopRequest}
        onPause={handlePause}
        onResume={handleResume}
        onClose={handleCloseComplete}
      />

      <StopConfirmDialog
        isOpen={showStopDialog}
        onCancel={handleStopCancel}
        onConfirm={handleStopConfirm}
      />
    </div>
  );
}

export default function SyncPage() {
  return (
    <AuthGuard>
      <SyncContent />
    </AuthGuard>
  );
}
