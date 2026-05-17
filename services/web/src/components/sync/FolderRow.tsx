"use client";

import type { WatchedFolder, ContentType } from "@/lib/types/drive";

interface FolderRowProps {
  folder: WatchedFolder;
  depth: number;
  hasChildren: boolean;
  isExpanded: boolean;
  isToggling: boolean;
  disabled?: boolean;
  onToggle: () => void;
  onExpand: () => void;
  onContentTypeChange: (types: ContentType[]) => void;
}

function contentTypeValue(types: ContentType[]): string {
  if (types.includes("video") && types.includes("image")) return "both";
  if (types.includes("image")) return "image";
  return "video";
}

function parseContentTypes(value: string): ContentType[] {
  if (value === "both") return ["video", "image"];
  if (value === "image") return ["image"];
  return ["video"];
}

export function FolderRow({
  folder,
  depth,
  hasChildren,
  isExpanded,
  isToggling,
  disabled = false,
  onToggle,
  onExpand,
  onContentTypeChange,
}: FolderRowProps) {
  const paddingLeft = depth * 24;

  return (
    <div
      className="flex items-center gap-2 border-b border-gray-100 py-2 pr-3 transition-colors hover:bg-gray-50"
      style={{ paddingLeft: `${paddingLeft + 12}px` }}
    >
      <button
        type="button"
        onClick={hasChildren ? onExpand : undefined}
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded text-gray-400 ${
          hasChildren ? "hover:bg-gray-200 cursor-pointer" : "invisible"
        }`}
        tabIndex={hasChildren ? 0 : -1}
        aria-label={isExpanded ? "접기" : "펼치기"}
      >
        <svg
          className={`h-3 w-3 transition-transform ${isExpanded ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>

      <label className="flex shrink-0 items-center">
        <input
          type="checkbox"
          checked={folder.sync_enabled}
          onChange={onToggle}
          disabled={isToggling || disabled}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 disabled:opacity-50"
        />
      </label>

      <svg className="h-4 w-4 shrink-0 text-amber-500" fill="currentColor" viewBox="0 0 20 20">
        <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
      </svg>

      <span className="min-w-0 flex-1 truncate text-sm text-gray-800">
        {folder.folder_name}
      </span>

      {folder.sync_enabled && (
        <select
          value={contentTypeValue(folder.content_types as ContentType[])}
          onChange={(e) => onContentTypeChange(parseContentTypes(e.target.value))}
          disabled={disabled}
          className="shrink-0 rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 focus:border-blue-400 focus:outline-none disabled:opacity-50"
        >
          <option value="video">동영상</option>
          <option value="image">이미지</option>
          <option value="both">동영상+이미지</option>
        </select>
      )}

      {folder.file_count_cached > 0 && (
        <span className="shrink-0 text-xs text-gray-400">
          {folder.file_count_cached.toLocaleString()}개
        </span>
      )}
    </div>
  );
}
