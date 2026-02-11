"use client";

import type { VideoSummary } from "@/lib/types";
import { formatTimestamp } from "@/lib/api/utils";

interface VideoCardProps {
  video: VideoSummary;
  onSelect: (videoId: string) => void;
}

function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

export function VideoCard({ video, onSelect }: VideoCardProps) {
  const duration = video.last_scene_end_ms - video.first_scene_start_ms;
  const allTags = [...video.keyword_tags, ...video.product_tags].slice(0, 5);

  return (
    <button
      onClick={() => onSelect(video.video_id)}
      className="card p-4 w-full text-left hover:shadow-md transition-shadow"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-gray-900 truncate" title={video.video_title || video.video_id}>
            {video.video_title || video.video_id}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">
            {video.library_name || "Unknown library"}
          </p>
        </div>
        <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full bg-gray-100 text-gray-700 flex-shrink-0">
          {video.source_type === "gdrive" ? "Drive" : video.source_type === "removable_disk" ? "Disk" : "Unknown"}
        </span>
      </div>

      <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
        <span>{video.scene_count} {video.scene_count === 1 ? "scene" : "scenes"}</span>
        {duration > 0 && <span>{formatTimestamp(duration)}</span>}
        {video.people_count > 0 && (
          <span>{video.people_count} {video.people_count === 1 ? "person" : "people"}</span>
        )}
      </div>

      {allTags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {allTags.map((tag) => (
            <span
              key={tag}
              className="inline-block px-1.5 py-0.5 text-xs bg-blue-50 text-blue-700 rounded"
            >
              {tag}
            </span>
          ))}
        </div>
      )}

      {video.latest_ingest_time && (
        <p className="mt-2 text-xs text-gray-400">
          Ingested {formatRelativeTime(video.latest_ingest_time)}
        </p>
      )}
    </button>
  );
}
