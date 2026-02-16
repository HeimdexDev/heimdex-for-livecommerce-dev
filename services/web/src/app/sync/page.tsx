"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@/lib/auth";
import { getDevices } from "@/lib/api/devices";
import { createFolderIntent } from "@/lib/api/agent-intents";
import { getAgentStatus } from "@/lib/agent";
import type { AgentState } from "@/lib/agent";
import { AuthGuard } from "@/components/AuthGuard";
import { SyncSourceCard } from "@/components/sync/SyncSourceCard";
import { UploadProgress } from "@/components/sync/UploadProgress";
import { StopConfirmDialog } from "@/components/sync/StopConfirmDialog";
import type { DeviceListItem } from "@/lib/types";

type UploadState = "hidden" | "uploading" | "paused" | "complete" | "error";

const POLL_INTERVAL_MS = 2000;
const MAX_UNREACHABLE_COUNT = 5;

const SYNC_SOURCES = [
  { title: "클라우드", disabled: true },
  { title: "외장하드", disabled: true },
  { title: "로컬 파일", disabled: false },
  { title: "수동 파일", disabled: true },
] as const;

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
  const pollingRef = useRef(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const unreachableCountRef = useRef(0);

  useEffect(() => {
    async function loadDevices() {
      try {
        const res = await getDevices(getAccessToken);
        setDevices(res.devices.filter((d) => !d.is_revoked));
      } catch {
        setDevices([]);
      }
    }
    loadDevices();
  }, [getAccessToken]);

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

    if (devices.length === 0) {
      setError("등록된 디바이스가 없습니다. 설정 > 디바이스에서 먼저 디바이스를 등록해주세요.");
      return;
    }

    try {
      const device = devices[0];
      const intent = await createFolderIntent(getAccessToken, device.device_id);

      window.open(intent.deep_link_url, "_blank");

      setProgress(0);
      setStatusText(undefined);
      setUploadState("uploading");
      startPolling();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "인텐트 생성에 실패했습니다.";
      setError(message);
    }
  }, [uploadState, devices, getAccessToken, startPolling]);

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
