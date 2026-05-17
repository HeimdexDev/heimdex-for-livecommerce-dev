"use client";

import { useState, useEffect, useCallback } from "react";
import { browseDriveFolders } from "@/lib/api/drive";
import type { DriveFolderItem } from "@/lib/types";
import { ApiError } from "@/lib/types/api";

interface BreadcrumbItem {
  id: string;
  name: string;
}

interface DriveFolderBrowserProps {
  onFolderSelected: (folderId: string, folderName: string, folderPath: string) => void;
  onClose: () => void;
  getAccessToken: () => Promise<string | null>;
  onAuthExpired?: () => void;
}

function FolderIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className="h-5 w-5"
      viewBox="0 0 20 20"
      fill="currentColor"
    >
      <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="flex items-center gap-3 rounded-lg border border-gray-100 bg-white px-4 py-3"
        >
          <div className="h-8 w-8 shrink-0 animate-pulse rounded-lg bg-gray-200" />
          <div className="min-w-0 flex-1">
            <div className="h-4 w-2/3 animate-pulse rounded bg-gray-200" />
          </div>
          <div className="h-7 w-14 animate-pulse rounded-md bg-gray-200" />
        </div>
      ))}
    </div>
  );
}

export function DriveFolderBrowser({
  onFolderSelected,
  onClose,
  getAccessToken,
  onAuthExpired,
}: DriveFolderBrowserProps) {
  const [folders, setFolders] = useState<DriveFolderItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [breadcrumbs, setBreadcrumbs] = useState<BreadcrumbItem[]>([
    { id: "root", name: "내 드라이브" },
  ]);

  const currentParentId = breadcrumbs[breadcrumbs.length - 1].id;

  const loadFolders = useCallback(async (parentId: string) => {
    setLoading(true);
    try {
      const resp = await browseDriveFolders(parentId, getAccessToken);
      setFolders(resp.folders);
    } catch (err) {
      if (err instanceof ApiError && err.detail.includes("만료") && onAuthExpired) {
        onAuthExpired();
      }
      setFolders([]);
    } finally {
      setLoading(false);
    }
  }, [getAccessToken, onAuthExpired]);

  useEffect(() => {
    loadFolders(currentParentId);
  }, [currentParentId, loadFolders]);

  const handleDrillIn = useCallback((folder: DriveFolderItem) => {
    setBreadcrumbs((prev) => [...prev, { id: folder.id, name: folder.name }]);
  }, []);

  const handleBreadcrumbClick = useCallback((index: number) => {
    setBreadcrumbs((prev) => prev.slice(0, index + 1));
  }, []);

  const buildFolderPath = useCallback((folderName: string) => {
    const pathParts = breadcrumbs.map((b) => b.name);
    pathParts.push(folderName);
    return pathParts.join("/");
  }, [breadcrumbs]);

  const handleSelect = useCallback((folder: DriveFolderItem) => {
    const path = buildFolderPath(folder.name);
    onFolderSelected(folder.id, folder.name, path);
  }, [buildFolderPath, onFolderSelected]);

  return (
    <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">
          폴더 선택
        </h3>
        <button
          onClick={onClose}
          className="rounded-md p-1 text-gray-400 hover:bg-gray-200 hover:text-gray-600"
        >
          <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        </button>
      </div>

      {/* Breadcrumbs */}
      <nav className="mb-3 flex items-center gap-1 text-xs text-gray-500">
        {breadcrumbs.map((crumb, index) => (
          <span key={crumb.id} className="flex items-center gap-1">
            {index > 0 && <span className="text-gray-300">/</span>}
            <button
              onClick={() => handleBreadcrumbClick(index)}
              className={
                index === breadcrumbs.length - 1
                  ? "font-medium text-gray-700"
                  : "hover:text-blue-600 hover:underline"
              }
              disabled={index === breadcrumbs.length - 1}
            >
              {crumb.name}
            </button>
          </span>
        ))}
      </nav>

      {/* Folder list */}
      {loading ? (
        <LoadingSkeleton />
      ) : folders.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 py-8 text-center">
          <p className="text-sm text-gray-400">
            하위 폴더가 없습니다.
          </p>
        </div>
      ) : (
        <div className="max-h-80 space-y-1.5 overflow-y-auto">
          {folders.map((folder) => (
            <div
              key={folder.id}
              className="group flex items-center gap-3 rounded-lg border border-gray-100 bg-white px-4 py-3 transition-colors hover:border-blue-200 hover:bg-blue-50/30"
            >
              <button
                onClick={() => handleDrillIn(folder)}
                className="flex min-w-0 flex-1 items-center gap-3"
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-500">
                  <FolderIcon />
                </div>
                <span className="truncate text-sm font-medium text-gray-800 group-hover:text-blue-700">
                  {folder.name}
                </span>
              </button>
              <button
                onClick={() => handleSelect(folder)}
                className="shrink-0 rounded-md bg-blue-500 px-3 py-1 text-xs font-medium text-white opacity-0 transition-opacity hover:bg-blue-600 group-hover:opacity-100"
              >
                선택
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
