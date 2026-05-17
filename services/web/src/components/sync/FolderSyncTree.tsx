"use client";

import { useCallback, useMemo, useState } from "react";
import type { WatchedFolder, DriveInfo, ContentType, FolderDisableImpact } from "@/lib/types/drive";
import { getFolderDisableImpact } from "@/lib/api/drive";
import { useAuth } from "@/lib/auth";
import { FolderRow } from "./FolderRow";
import { DisableFolderConfirmDialog } from "./DisableFolderConfirmDialog";

interface FolderSyncTreeProps {
  folders: WatchedFolder[];
  drives: DriveInfo[];
  onToggle: (folderId: string, enabled: boolean) => Promise<void>;
  onContentTypeChange: (folderId: string, types: ContentType[]) => Promise<void>;
  onRefresh: () => Promise<void>;
  isRefreshing: boolean;
  disabled?: boolean;
}

interface TreeNode {
  folder: WatchedFolder;
  children: TreeNode[];
}

function buildTree(
  folders: WatchedFolder[],
  connectionId: string,
): TreeNode[] {
  const connectionFolders = folders.filter((f) => f.connection_id === connectionId);
  const byParent = new Map<string | null, WatchedFolder[]>();

  for (const folder of connectionFolders) {
    const key = folder.parent_folder_id;
    const existing = byParent.get(key) || [];
    existing.push(folder);
    byParent.set(key, existing);
  }

  const connectionFolderIds = new Set(connectionFolders.map((f) => f.google_folder_id));

  function buildNodes(parentId: string): TreeNode[] {
    const children = byParent.get(parentId) || [];
    return children
      .sort((a, b) => a.folder_name.localeCompare(b.folder_name))
      .map((folder) => ({
        folder,
        children: buildNodes(folder.google_folder_id),
      }));
  }

  const roots = connectionFolders.filter(
    (f) => f.parent_folder_id === null || !connectionFolderIds.has(f.parent_folder_id),
  );

  return roots
    .sort((a, b) => a.folder_name.localeCompare(b.folder_name))
    .map((folder) => ({
      folder,
      children: buildNodes(folder.google_folder_id),
    }));
}

export function FolderSyncTree({
  folders,
  drives,
  onToggle,
  onContentTypeChange,
  onRefresh,
  isRefreshing,
  disabled = false,
}: FolderSyncTreeProps) {
  const { getAccessToken } = useAuth();
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [expandedDrives, setExpandedDrives] = useState<Set<string>>(
    new Set(drives.map((d) => d.connection_id)),
  );
  const [togglingIds, setTogglingIds] = useState<Set<string>>(new Set());
  const [disableTarget, setDisableTarget] = useState<WatchedFolder | null>(null);
  const [isDisabling, setIsDisabling] = useState(false);
  const [impact, setImpact] = useState<FolderDisableImpact | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);

  const trees = useMemo(() => {
    const result: { drive: DriveInfo; nodes: TreeNode[]; enabledCount: number }[] = [];
    for (const drive of drives) {
      const nodes = buildTree(folders, drive.connection_id);
      const enabledCount = folders.filter(
        (f) => f.connection_id === drive.connection_id && f.sync_enabled,
      ).length;
      result.push({ drive, nodes, enabledCount });
    }
    return result;
  }, [folders, drives]);

  const handleToggle = useCallback(
    async (folder: WatchedFolder) => {
      if (folder.sync_enabled) {
        setDisableTarget(folder);
        setImpactLoading(true);
        setImpact(null);
        try {
          const result = await getFolderDisableImpact(folder.id, getAccessToken);
          setImpact(result);
        } catch {
          setImpact({ video_count: 0, image_count: 0, total_count: 0 });
        } finally {
          setImpactLoading(false);
        }
        return;
      }
      setTogglingIds((prev) => new Set(prev).add(folder.id));
      try {
        await onToggle(folder.id, true);
      } finally {
        setTogglingIds((prev) => {
          const next = new Set(prev);
          next.delete(folder.id);
          return next;
        });
      }
    },
    [onToggle, getAccessToken],
  );

  const handleDisableConfirm = useCallback(async () => {
    if (!disableTarget) return;
    setIsDisabling(true);
    setTogglingIds((prev) => new Set(prev).add(disableTarget.id));
    try {
      await onToggle(disableTarget.id, false);
      setDisableTarget(null);
      setImpact(null);
    } finally {
      setIsDisabling(false);
      setTogglingIds((prev) => {
        const next = new Set(prev);
        if (disableTarget) next.delete(disableTarget.id);
        return next;
      });
    }
  }, [disableTarget, onToggle]);

  const handleContentTypeChange = useCallback(
    async (folderId: string, types: ContentType[]) => {
      await onContentTypeChange(folderId, types);
    },
    [onContentTypeChange],
  );

  const toggleExpand = useCallback((folderId: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folderId)) next.delete(folderId);
      else next.add(folderId);
      return next;
    });
  }, []);

  const toggleDriveSection = useCallback((connectionId: string) => {
    setExpandedDrives((prev) => {
      const next = new Set(prev);
      if (next.has(connectionId)) next.delete(connectionId);
      else next.add(connectionId);
      return next;
    });
  }, []);

  function renderNodes(nodes: TreeNode[], depth: number) {
    return nodes.map((node) => {
      const hasChildren = node.children.length > 0;
      const isExpanded = expandedFolders.has(node.folder.google_folder_id);
      return (
        <div key={node.folder.id}>
          <FolderRow
            folder={node.folder}
            depth={depth}
            hasChildren={hasChildren}
            isExpanded={isExpanded}
            isToggling={togglingIds.has(node.folder.id)}
            disabled={disabled}
            onToggle={() => handleToggle(node.folder)}
            onExpand={() => toggleExpand(node.folder.google_folder_id)}
            onContentTypeChange={(types) => handleContentTypeChange(node.folder.id, types)}
          />
          {hasChildren && isExpanded && renderNodes(node.children, depth + 1)}
        </div>
      );
    });
  }

  return (
    <div className="mt-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">폴더 동기화 설정</h3>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50"
        >
          <svg
            className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
          {isRefreshing ? "불러오는 중..." : "새로고침"}
        </button>
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        {trees.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-gray-500">
            폴더를 불러오려면 &quot;새로고침&quot; 버튼을 눌러주세요.
          </div>
        ) : (
          trees.map(({ drive, nodes, enabledCount }) => {
            const isExpanded = expandedDrives.has(drive.connection_id);
            const driveName =
              drive.scope_type === "my_drive"
                ? "내 드라이브"
                : drive.drive_name || "공유 드라이브";
            return (
              <div key={drive.connection_id}>
                <button
                  type="button"
                  onClick={() => toggleDriveSection(drive.connection_id)}
                  className="flex w-full items-center gap-2 border-b border-gray-200 bg-gray-50 px-3 py-2.5 text-left transition-colors hover:bg-gray-100"
                >
                  <svg
                    className={`h-3.5 w-3.5 text-gray-500 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                  <span className="text-sm font-medium text-gray-800">{driveName}</span>
                  {enabledCount > 0 && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">
                      {enabledCount}개 폴더 동기화 중
                    </span>
                  )}
                </button>
                {isExpanded && (
                  <div>
                    {nodes.length === 0 ? (
                      <div className="px-4 py-3 text-sm text-gray-400">
                        폴더가 없습니다
                      </div>
                    ) : (
                      renderNodes(nodes, 0)
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      <DisableFolderConfirmDialog
        isOpen={disableTarget !== null}
        folderName={disableTarget?.folder_name ?? null}
        videoCount={impact?.video_count ?? 0}
        imageCount={impact?.image_count ?? 0}
        isLoading={impactLoading}
        isDisabling={isDisabling}
        onCancel={() => { setDisableTarget(null); setImpact(null); }}
        onConfirm={handleDisableConfirm}
      />
    </div>
  );
}
