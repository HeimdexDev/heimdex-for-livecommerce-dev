"use client";

import type { VideoFacets, VideoFilters } from "@/lib/types";
import { cn } from "@/lib/utils";

interface VideoFilterPanelProps {
  facets: VideoFacets | null;
  filters: VideoFilters;
  onChange: (filters: VideoFilters) => void;
}

export function VideoFilterPanel({ facets, filters, onChange }: VideoFilterPanelProps) {
  const handleLibraryChange = (libraryId: string | undefined) => {
    onChange({ ...filters, library_id: libraryId });
  };

  const handleSourceChange = (sourceType: "gdrive" | "removable_disk" | undefined) => {
    onChange({ ...filters, source_type: sourceType });
  };

  const handleSortChange = (sort: "latest" | "oldest") => {
    onChange({ ...filters, sort });
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-gray-900 mb-2">Sort</h3>
        <div className="space-y-1">
          {(["latest", "oldest"] as const).map((opt) => (
            <button
              key={opt}
              onClick={() => handleSortChange(opt)}
              className={cn(
                "block w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors",
                filters.sort === opt
                  ? "bg-primary-600 text-white"
                  : "text-gray-700 hover:bg-gray-100",
              )}
            >
              {opt === "latest" ? "Newest first" : "Oldest first"}
            </button>
          ))}
        </div>
      </div>

      {facets && facets.libraries.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-2">Library</h3>
          <div className="space-y-1">
            <button
              onClick={() => handleLibraryChange(undefined)}
              className={cn(
                "block w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors",
                !filters.library_id
                  ? "bg-primary-600 text-white"
                  : "text-gray-700 hover:bg-gray-100",
              )}
            >
              All libraries
            </button>
            {facets.libraries.map((lib) => (
              <button
                key={lib.id}
                onClick={() => handleLibraryChange(lib.id)}
                className={cn(
                  "block w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors",
                  filters.library_id === lib.id
                    ? "bg-primary-600 text-white"
                    : "text-gray-700 hover:bg-gray-100",
                )}
              >
                <span className="truncate">{lib.name || lib.id}</span>
                <span className="ml-1 text-xs opacity-70">({lib.count})</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {facets && facets.source_types.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-gray-900 mb-2">Source</h3>
          <div className="space-y-1">
            <button
              onClick={() => handleSourceChange(undefined)}
              className={cn(
                "block w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors",
                !filters.source_type
                  ? "bg-primary-600 text-white"
                  : "text-gray-700 hover:bg-gray-100",
              )}
            >
              All sources
            </button>
            {facets.source_types.map((src) => (
              <button
                key={src.id}
                onClick={() =>
                  handleSourceChange(src.id as "gdrive" | "removable_disk")
                }
                className={cn(
                  "block w-full text-left px-3 py-1.5 text-sm rounded-lg transition-colors",
                  filters.source_type === src.id
                    ? "bg-primary-600 text-white"
                    : "text-gray-700 hover:bg-gray-100",
                )}
              >
                {src.id === "gdrive" ? "Google Drive" : "Removable Disk"}
                <span className="ml-1 text-xs opacity-70">({src.count})</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
