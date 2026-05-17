"use client";

import { cn } from "@/lib/utils";
import type { DriveFolderInfo } from "@/lib/types";

interface DriveFolderListProps {
  folders: DriveFolderInfo[];
  totalFiles: number;
  loading?: boolean;
}

function FolderRow({ folder }: { folder: DriveFolderInfo }) {
  const allIndexed = folder.indexed_count === folder.file_count && folder.file_count > 0;
  const hasProcessing = folder.processing_count > 0 || folder.pending_count > 0;
  const hasFailed = folder.failed_count > 0;

  const dotColor = hasFailed
    ? "bg-red-400"
    : hasProcessing
      ? "bg-blue-400"
      : allIndexed
        ? "bg-emerald-400"
        : "bg-gray-300";

  return (
    <div className="flex items-center gap-4 rounded-lg border border-gray-100 bg-white px-5 py-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-500">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-5 w-5"
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path d="M5.5 16a3.5 3.5 0 01-.369-6.98 4 4 0 117.753-1.977A4.5 4.5 0 1113.5 16h-8z" />
        </svg>
      </div>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-gray-900">
          {folder.folder_path}
        </p>
        <p className="truncate text-xs text-gray-400">
          {folder.indexed_count}/{folder.file_count} 완료
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
          {folder.file_count}
          <span className="ml-0.5 text-gray-400">개 파일</span>
        </span>

        <span className={cn("h-2 w-2 rounded-full", dotColor)} />
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="flex items-center gap-4 rounded-lg border border-gray-100 bg-white px-5 py-4"
        >
          <div className="h-10 w-10 shrink-0 animate-pulse rounded-lg bg-gray-200" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-3.5 w-3/5 animate-pulse rounded bg-gray-200" />
            <div className="h-3 w-2/5 animate-pulse rounded bg-gray-200" />
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <div className="h-5 w-16 animate-pulse rounded-full bg-gray-200" />
            <div className="h-2 w-2 animate-pulse rounded-full bg-gray-200" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function DriveFolderList({
  folders,
  loading = false,
}: DriveFolderListProps) {
  return (
    <div className="mt-8">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900">
          드라이브 폴더
          {folders.length > 0 && !loading && (
            <span className="ml-2 text-sm font-normal text-gray-400">
              {folders.length}개
            </span>
          )}
        </h2>
      </div>

      {loading ? (
        <LoadingSkeleton />
      ) : folders.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 py-12 text-center">
          <p className="text-sm text-gray-400">
            연결된 드라이브 폴더가 없습니다.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {folders.map((folder) => (
            <FolderRow key={folder.folder_path} folder={folder} />
          ))}
        </div>
      )}
    </div>
  );
}
