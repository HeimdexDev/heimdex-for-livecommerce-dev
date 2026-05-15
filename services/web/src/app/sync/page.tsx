"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@/lib/auth";
import { getDevices } from "@/lib/api/devices";
import {
  getDriveStatus,
  getDriveConnections,
  triggerDriveSync,
  getDriveFolders,
  getOAuthStatus,
  getOAuthAuthorizeUrl,
  disconnectOAuth,
  createFolderConnection,
  getDriveConnectionProgress,
  deleteDriveConnection,
  getWatchedFolders,
  enumerateFolders,
  toggleFolderSync,
  updateFolderContentTypes,
} from "@/lib/api/drive";
import { DriveSyncProgress as DriveSyncProgressComponent } from "@/components/sync/DriveSyncProgress";
import {
  getAgentStatus,
  getAgentSources,
  deleteAgentSource,
  renameAgentSource,
  pickFolder,
} from "@/lib/agent";
import type { AgentState, AgentSource } from "@/lib/agent";
import { AuthGuard } from "@/components/AuthGuard";
import { SyncSourceCard } from "@/components/sync/SyncSourceCard";
import type { ConnectionStatus, ProcessingStatus } from "@/components/sync/SyncSourceCard";
import { SyncedFolderList } from "@/components/sync/SyncedFolderList";
import { DriveFolderList } from "@/components/sync/DriveFolderList";
import { UploadProgress } from "@/components/sync/UploadProgress";
import { StopConfirmDialog } from "@/components/sync/StopConfirmDialog";
import { DriveFolderBrowser } from "@/components/sync/DriveFolderBrowser";
import { DeleteConnectionDialog } from "@/components/sync/DeleteConnectionDialog";
import { OAuthExpiredDialog, type OAuthReauthReason } from "@/components/sync/OAuthExpiredDialog";
import { FolderSyncTree } from "@/components/sync/FolderSyncTree";
import type { DeviceListItem, DriveStatusResponse, DriveFolderInfo, DriveConnectionResponse, DriveOAuthStatus, DriveSyncProgress } from "@/lib/types";
import type { FolderTreeResponse, ContentType } from "@/lib/types/drive";
import { ApiError } from "@/lib/types/api";

type UploadState = "hidden" | "uploading" | "paused" | "complete" | "error";

const POLL_INTERVAL_MS = 2000;
const DEVICE_POLL_INTERVAL_MS = 30_000;
const MAX_UNREACHABLE_COUNT = 5;
const AGENT_STALE_MINUTES = 5;

function deriveDriveConnectionStatus(
  drive: DriveStatusResponse | null,
): ConnectionStatus {
  if (!drive) return "unknown";
  if (!drive.connected) return "offline";
  return drive.connection_status === "active" ? "connected" : "offline";
}

function deriveDriveProcessingStatus(
  drive: DriveStatusResponse | null,
): ProcessingStatus {
  if (!drive || !drive.connected) return "unknown";
  if (drive.failed > 0 && drive.processing === 0 && drive.pending === 0) return "error";
  if (drive.processing > 0 || drive.pending > 0) return "processing";
  if (drive.indexed > 0) return "complete";
  return "unknown";
}

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
  const { getAccessToken, user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [uploadState, setUploadState] = useState<UploadState>("hidden");
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState<string | undefined>();
  const [showStopDialog, setShowStopDialog] = useState(false);
  const [devices, setDevices] = useState<DeviceListItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("unknown");
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus>("unknown");
  const [lastSeenAt, setLastSeenAt] = useState<string | null>(null);
  const [sources, setSources] = useState<AgentSource[]>([]);
  const [showFolders, setShowFolders] = useState(false);
  const [driveStatus, setDriveStatus] = useState<DriveStatusResponse | null>(null);
  const [showDriveFolders, setShowDriveFolders] = useState(false);
  const [driveFolders, setDriveFolders] = useState<DriveFolderInfo[]>([]);
  const [driveFoldersTotal, setDriveFoldersTotal] = useState(0);
  const [driveFoldersLoading, setDriveFoldersLoading] = useState(false);
  const [driveSyncing, setDriveSyncing] = useState(false);
  const [driveConnections, setDriveConnections] = useState<DriveConnectionResponse[]>([]);
  const [oauthStatus, setOauthStatus] = useState<DriveOAuthStatus | null>(null);
  const [showFolderBrowser, setShowFolderBrowser] = useState(false);
  const [oauthLoading, setOauthLoading] = useState(false);
  const [syncProgress, setSyncProgress] = useState<DriveSyncProgress | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DriveConnectionResponse | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [folderTree, setFolderTree] = useState<FolderTreeResponse | null>(null);
  const [isEnumerating, setIsEnumerating] = useState(false);
  const [showReauthDialog, setShowReauthDialog] = useState(false);
  const [reauthReason, setReauthReason] = useState<OAuthReauthReason>("expired");
  const syncProgressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
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

  const loadSources = useCallback(async () => {
    const list = await getAgentSources();
    setSources(list);
  }, []);

  const loadDriveStatus = useCallback(async () => {
    try {
      const status = await getDriveStatus(getAccessToken);
      setDriveStatus(status);
    } catch {
      setDriveStatus(null);
    }
  }, [getAccessToken]);

  const loadDriveConnections = useCallback(async () => {
    try {
      const conns = await getDriveConnections(getAccessToken);
      setDriveConnections(conns);
    } catch {
      setDriveConnections([]);
    }
  }, [getAccessToken]);

  const loadOAuthStatus = useCallback(async () => {
    try {
      const status = await getOAuthStatus(getAccessToken);
      setOauthStatus(status);
      // Auto-pop the reauth dialog when the stored token is missing
      // drive.readonly. ``scope_ok === false`` is an explicit signal
      // from the API; ``null`` means "legacy token, unknown" — leave
      // it alone so we don't false-pop existing connections.
      if (status.connected && status.scope_ok === false) {
        setReauthReason("missing_scope");
        setShowReauthDialog(true);
      }
    } catch {
      setOauthStatus(null);
    }
  }, [getAccessToken]);

  const loadFolderTree = useCallback(async () => {
    try {
      const tree = await getWatchedFolders(getAccessToken);
      setFolderTree(tree);
    } catch {
      // First load may fail if not enumerated yet
    }
  }, [getAccessToken]);

  const handleEnumerate = useCallback(async () => {
    setIsEnumerating(true);
    setError(null);
    try {
      const tree = await enumerateFolders(getAccessToken);
      setFolderTree(tree);
    } catch (err) {
      if (err instanceof ApiError && err.detail.includes("만료")) {
        setReauthReason("expired");
        setShowReauthDialog(true);
      } else if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        console.error("Failed to enumerate folders:", err);
      }
    } finally {
      setIsEnumerating(false);
    }
  }, [getAccessToken]);

  const handleFolderToggle = useCallback(async (folderId: string, enabled: boolean) => {
    const result = await toggleFolderSync(folderId, enabled, getAccessToken);
    setFolderTree((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        folders: prev.folders.map((f) =>
          f.id === folderId ? result.folder : f,
        ),
      };
    });
  }, [getAccessToken]);

  const handleContentTypeChange = useCallback(async (folderId: string, types: ContentType[]) => {
    const updated = await updateFolderContentTypes(folderId, types, getAccessToken);
    setFolderTree((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        folders: prev.folders.map((f) =>
          f.id === folderId ? updated : f,
        ),
      };
    });
  }, [getAccessToken]);

  const loadSyncProgress = useCallback(async () => {
    const activeConn = driveConnections.find(c => c.status === "active");
    if (!activeConn) return;
    try {
      const prog = await getDriveConnectionProgress(activeConn.id, getAccessToken);
      setSyncProgress(prog);
    } catch {
    }
  }, [driveConnections, getAccessToken]);

  const loadDriveFolders = useCallback(async () => {
    const activeConn = driveConnections.find(c => c.status === "active");
    if (!activeConn) return;
    setDriveFoldersLoading(true);
    try {
      const resp = await getDriveFolders(activeConn.id, getAccessToken);
      setDriveFolders(resp.folders);
      setDriveFoldersTotal(resp.total_files);
    } catch {
      setDriveFolders([]);
      setDriveFoldersTotal(0);
    } finally {
      setDriveFoldersLoading(false);
    }
  }, [driveConnections, getAccessToken]);

  useEffect(() => {
    loadDevices();
    loadSources();
    loadDriveStatus();
    loadDriveConnections();
    loadOAuthStatus();
    loadFolderTree();
    const id = setInterval(() => { loadDevices(); loadSources(); loadDriveStatus(); loadDriveConnections(); loadOAuthStatus(); }, DEVICE_POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadDevices, loadSources, loadDriveStatus, loadDriveConnections, loadOAuthStatus, loadFolderTree]);

  // OAuth callback can redirect back here with
  // ``?drive_oauth_error=missing_drive_scope`` when the user clicked
  // through Google's consent screen but unchecked Drive. Pop the
  // reauth dialog with the scope-specific copy and strip the param
  // so a hard refresh doesn't re-pop after the user fixes it.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("drive_oauth_error") === "missing_drive_scope") {
      setReauthReason("missing_scope");
      setShowReauthDialog(true);
      params.delete("drive_oauth_error");
      const qs = params.toString();
      const next = qs
        ? `${window.location.pathname}?${qs}`
        : window.location.pathname;
      window.history.replaceState(null, "", next);
    }
  }, []);

  useEffect(() => {
    if (showDriveFolders) {
      loadDriveFolders();
    }
  }, [showDriveFolders, loadDriveFolders]);

  useEffect(() => {
    if (syncProgressIntervalRef.current) {
      clearInterval(syncProgressIntervalRef.current);
      syncProgressIntervalRef.current = null;
    }
    loadSyncProgress();
    const isActive = (syncProgress?.processing ?? 0) > 0 || (syncProgress?.pending ?? 0) > 0;
    const intervalMs = isActive ? 5000 : 30000;
    syncProgressIntervalRef.current = setInterval(loadSyncProgress, intervalMs);
    return () => {
      if (syncProgressIntervalRef.current) {
        clearInterval(syncProgressIntervalRef.current);
        syncProgressIntervalRef.current = null;
      }
    };
  }, [driveConnections, loadSyncProgress, syncProgress?.processing, syncProgress?.pending]);

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
      loadSources();
      startPolling();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "폴더 추가에 실패했습니다.";
      setError(message);
      setUploadState("hidden");
      setStatusText(undefined);
    }
  }, [uploadState, startPolling, loadSources]);

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

  const handleCardClick = useCallback((title: string) => {
    if (title === "로컬 파일") {
      setShowFolders((prev) => !prev);
      setShowDriveFolders(false);
    } else if (title === "클라우드") {
      setShowDriveFolders((prev) => !prev);
      setShowFolders(false);
    }
  }, []);

  const handleDriveSync = useCallback(async () => {
    const activeConn = driveConnections.find(c => c.status === "active");
    if (!activeConn) return;
    setDriveSyncing(true);
    try {
      await triggerDriveSync(activeConn.id, getAccessToken);
      setTimeout(() => {
        loadDriveStatus();
        if (showDriveFolders) loadDriveFolders();
      }, 3000);
    } catch (err) {
      console.error("Drive sync trigger failed:", err);
    } finally {
      setTimeout(() => setDriveSyncing(false), 3000);
    }
  }, [driveConnections, getAccessToken, loadDriveStatus, showDriveFolders, loadDriveFolders]);

  const handleConnectGoogle = useCallback(async () => {
    setOauthLoading(true);
    try {
      const { authorize_url } = await getOAuthAuthorizeUrl(getAccessToken);
      window.location.href = authorize_url;
    } catch (err) {
      console.error("OAuth authorize failed:", err);
      setOauthLoading(false);
    }
  }, [getAccessToken]);

  /** Re-authorize OAuth without disconnecting folders or deleting files.
   *  Reuses the same authorize → callback → upsert flow as initial connect. */
  const handleRefreshOAuth = handleConnectGoogle;

  const handleDisconnectGoogle = useCallback(async () => {
    setOauthLoading(true);
    try {
      await disconnectOAuth(getAccessToken);
      setOauthStatus({ connected: false, google_email: null, connected_at: null });
      setShowFolderBrowser(false);
      loadDriveConnections();
    } catch (err) {
      console.error("OAuth disconnect failed:", err);
    } finally {
      setOauthLoading(false);
    }
  }, [getAccessToken, loadDriveConnections]);

  const handleFolderSelected = useCallback(async (folderId: string, folderName: string, folderPath: string) => {
    const libraryId = driveConnections[0]?.library_id ?? null;
    try {
      await createFolderConnection(libraryId, folderId, folderName, folderPath, getAccessToken);
      setShowFolderBrowser(false);
      loadDriveConnections();
    } catch (err) {
      if (err instanceof ApiError && err.detail.includes("만료")) {
        setReauthReason("expired");
        setShowReauthDialog(true);
      } else {
        console.error("Failed to create folder connection:", err);
      }
    }
  }, [driveConnections, getAccessToken, loadDriveConnections]);

  const handleDeleteSource = useCallback(async (id: string) => {
    const ok = await deleteAgentSource(id);
    if (ok) loadSources();
  }, [loadSources]);

  const handleRenameSource = useCallback(async (id: string, name: string) => {
    const ok = await renameAgentSource(id, name);
    if (ok) loadSources();
  }, [loadSources]);

  const handleDeleteConnection = useCallback(async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      await deleteDriveConnection(deleteTarget.id, getAccessToken);
      setDeleteTarget(null);
      loadDriveConnections();
      loadDriveStatus();
    } catch (err) {
      console.error("Failed to delete connection:", err);
    } finally {
      setIsDeleting(false);
    }
  }, [deleteTarget, getAccessToken, loadDriveConnections, loadDriveStatus]);

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

      {!isAdmin && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-2 text-sm text-amber-700 mb-6">
          동기화 설정은 관리자만 변경할 수 있습니다.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <SyncSourceCard
          title="클라우드"
          onUpdate={handleDriveSync}
          onCardClick={() => handleCardClick("클라우드")}
          disabled={!driveStatus?.connected}
          isUploading={driveSyncing}
          selected={showDriveFolders}
          connectionStatus={deriveDriveConnectionStatus(driveStatus)}
          processingStatus={deriveDriveProcessingStatus(driveStatus)}
          lastAnalyzedAt={driveStatus?.last_indexed_at ?? null}
          fileCount={driveStatus?.connected ? driveStatus.total_files : undefined}
        />
        <SyncSourceCard
          title="외장하드"
          onUpdate={() => {}}
          disabled
        />
        <SyncSourceCard
          title="로컬 파일"
          onUpdate={handleStartUpload}
          onCardClick={() => handleCardClick("로컬 파일")}
          isUploading={isUploading}
          selected={showFolders}
          connectionStatus={connectionStatus}
          processingStatus={processingStatus}
          lastAnalyzedAt={lastSeenAt}
        />
        <SyncSourceCard
          title="수동 파일"
          onUpdate={() => {}}
          disabled
        />
      </div>

      {/* Google Drive OAuth Section */}
      <div className="mt-8">
        {oauthStatus?.connected ? (
          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-green-50">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-green-600" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M5.5 16a3.5 3.5 0 01-.369-6.98 4 4 0 117.753-1.977A4.5 4.5 0 1113.5 16h-8z" />
                  </svg>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-gray-900">Google 드라이브 연결됨</h3>
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                      <span className="h-1.5 w-1.5 rounded-full bg-green-500" />
                      연결됨
                    </span>
                  </div>
                  {oauthStatus.google_email && (
                    <p className="mt-0.5 text-xs text-gray-500">{oauthStatus.google_email}</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowFolderBrowser((prev) => !prev)}
                  disabled={!isAdmin}
                  className="rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
                >
                  폴더 추가
                </button>
                <button
                  onClick={handleRefreshOAuth}
                  disabled={oauthLoading || !isAdmin}
                  className="rounded-lg border border-blue-200 px-4 py-2 text-sm font-medium text-blue-600 transition-colors hover:bg-blue-50 disabled:opacity-50"
                >
                  {oauthLoading ? "갱신 중..." : "연결 갱신"}
                </button>
                <button
                  onClick={handleDisconnectGoogle}
                  disabled={oauthLoading || !isAdmin}
                  className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                >
                  연결 해제
                </button>
              </div>
            </div>

            {showFolderBrowser && (
              <DriveFolderBrowser
                onFolderSelected={handleFolderSelected}
                onClose={() => setShowFolderBrowser(false)}
                getAccessToken={getAccessToken}
                onAuthExpired={() => {
                  setShowFolderBrowser(false);
                  setReauthReason("expired");
                  setShowReauthDialog(true);
                }}
              />
            )}
          </div>
        ) : (
          <div className="rounded-xl border-2 border-dashed border-gray-200 bg-white p-6 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6 text-blue-500" viewBox="0 0 20 20" fill="currentColor">
                <path d="M5.5 16a3.5 3.5 0 01-.369-6.98 4 4 0 117.753-1.977A4.5 4.5 0 1113.5 16h-8z" />
              </svg>
            </div>
            <h3 className="mt-3 text-sm font-semibold text-gray-900">Google 드라이브 연결</h3>
            <p className="mt-1 text-xs text-gray-500">
              Google 계정을 연결하여 드라이브 폴더를 동기화하세요.
            </p>
            <button
              onClick={handleConnectGoogle}
              disabled={oauthLoading || !isAdmin}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-500 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
            >
              {oauthLoading ? "연결 중..." : "Google 드라이브 연결하기"}
            </button>
          </div>
        )}

        {/* Connection list — always visible regardless of OAuth status so users can delete disconnected connections */}
        {driveConnections.length > 0 && (
          <div className={oauthStatus?.connected ? "" : "mt-4 rounded-xl border border-gray-200 bg-white p-6"}>
            {/* Drive connections */}
            {driveConnections.filter((c) => c.scope_type === "drive").length > 0 && (
              <div className="mt-4 space-y-2">
                <h4 className="text-xs font-medium text-gray-500">공유 드라이브</h4>
                {driveConnections
                  .filter((c) => c.scope_type === "drive")
                  .map((conn) => (
                    <div
                      key={conn.id}
                      className="flex items-center gap-3 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-500">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                          <path d="M5.5 16a3.5 3.5 0 01-.369-6.98 4 4 0 117.753-1.977A4.5 4.5 0 1113.5 16h-8z" />
                        </svg>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-800">{conn.drive_name || "공유 드라이브"}</p>
                      </div>
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        conn.status === "active"
                          ? "bg-green-50 text-green-700"
                          : "bg-gray-100 text-gray-500"
                      }`}>
                        {conn.status === "active" ? "활성" : conn.status}
                      </span>
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(conn)}
                        disabled={!isAdmin}
                        className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                      >
                        삭제
                      </button>
                    </div>
                  ))}
              </div>
            )}

            {/* Folder connections */}
            {driveConnections.filter((c) => c.scope_type === "folder").length > 0 && (
              <div className="mt-4 space-y-2">
                <h4 className="text-xs font-medium text-gray-500">동기화 폴더</h4>
                {driveConnections
                  .filter((c) => c.scope_type === "folder")
                  .map((conn) => (
                    <div
                      key={conn.id}
                      className="flex items-center gap-3 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-500">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                          <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                        </svg>
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-gray-800">{conn.folder_name}</p>
                        {conn.folder_path && (
                          <p className="truncate text-xs text-gray-400">{conn.folder_path}</p>
                        )}
                      </div>
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                        conn.status === "active"
                          ? "bg-green-50 text-green-700"
                          : "bg-gray-100 text-gray-500"
                      }`}>
                        {conn.status === "active" ? "활성" : conn.status}
                      </span>
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(conn)}
                        disabled={!isAdmin}
                        className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                      >
                        삭제
                      </button>
                    </div>
                  ))}
              </div>
            )}

            <DriveSyncProgressComponent progress={syncProgress} />

            <div className="my-4 border-t border-gray-200" />

            <div>
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-semibold text-gray-800">폴더 동기화 설정</h4>
                <button
                  type="button"
                  onClick={handleEnumerate}
                  disabled={isEnumerating || !isAdmin}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className={`h-3.5 w-3.5 ${isEnumerating ? "animate-spin" : ""}`}
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
                  </svg>
                  {isEnumerating ? "불러오는 중..." : "폴더 목록 갱신"}
                </button>
              </div>
              {folderTree ? (
                <FolderSyncTree
                  folders={folderTree.folders}
                  drives={folderTree.drives}
                  onToggle={handleFolderToggle}
                  onContentTypeChange={handleContentTypeChange}
                  onRefresh={handleEnumerate}
                  isRefreshing={isEnumerating}
                  disabled={!isAdmin}
                />
              ) : (
                <p className="text-xs text-gray-400">
                  폴더 목록을 불러오려면 갱신 버튼을 눌러주세요.
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {showFolders && (
        <SyncedFolderList
          sources={sources}
          onAddFolder={handleStartUpload}
          onDelete={handleDeleteSource}
          onRename={handleRenameSource}
        />
      )}

      {showDriveFolders && (
        <DriveFolderList
          folders={driveFolders}
          totalFiles={driveFoldersTotal}
          loading={driveFoldersLoading}
        />
      )}

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

      <DeleteConnectionDialog
        isOpen={deleteTarget !== null}
        connectionName={deleteTarget?.drive_name || deleteTarget?.folder_name || null}
        isDeleting={isDeleting}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDeleteConnection}
      />

      <OAuthExpiredDialog
        isOpen={showReauthDialog}
        googleEmail={oauthStatus?.google_email ?? null}
        isLoading={oauthLoading}
        reason={reauthReason}
        onReconnect={() => {
          setShowReauthDialog(false);
          handleConnectGoogle();
        }}
        onClose={() => setShowReauthDialog(false)}
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
