"use client";

import type { VideoSummary } from "@/lib/types";
import { formatTimestamp } from "@/lib/api/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { cn } from "@/lib/utils";
import { OpenInDriveButton } from "@/components/OpenInDriveButton";
import { useOrgSettings } from "@/lib/orgSettings";
import { getVideoCardThumbnailClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

interface VideoCardProps {
  video: VideoSummary;
  onSelect: (videoId: string) => void;
  agentAvailable: boolean;
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

export function VideoCard({ video, onSelect, agentAvailable }: VideoCardProps) {
  const duration = video.last_scene_end_ms - video.first_scene_start_ms;
  const allTags = [...video.keyword_tags, ...video.product_tags].slice(0, 5);
  const { settings } = useOrgSettings();
  const aspectRatio = settings.thumbnail_aspect_ratio as ThumbnailAspectRatio;

  return (
    <button
      onClick={() => onSelect(video.video_id)}
      className="card p-4 w-full text-left hover:shadow-md transition-shadow"
    >
      <div className="flex gap-3">
        <SceneThumbnail
          videoId={video.video_id}
          sceneId={video.source_type === "gdrive" || video.source_type === "youtube" ? `${video.video_id}_scene_000` : undefined}
          agentAvailable={agentAvailable}
          className={cn("flex-shrink-0 rounded-lg", getVideoCardThumbnailClass(aspectRatio))}
          sourceType={video.source_type}
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 truncate" title={video.video_title || video.video_id}>
                {video.video_title || video.video_id}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">
                {video.library_name || "Unknown library"}
              </p>
              {video.source_path && (
                <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-1 min-w-0" title={video.source_path}>
                  <svg className="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M3 7a2 2 0 012-2h5l2 2h7a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
                    />
                  </svg>
                  <span className="truncate">{video.source_path}</span>
                </p>
              )}
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0">
              <OpenInDriveButton
                sourceType={video.source_type ?? "local"}
                webViewLink={video.web_view_link}
              />
              <span className={cn(
                "inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full",
                video.source_type === "gdrive"
                  ? "bg-blue-100 text-blue-700"
                  : video.source_type === "youtube"
                  ? "bg-red-100 text-red-700"
                  : video.source_type === "removable_disk"
                  ? "bg-orange-100 text-orange-700"
                  : video.source_type === "local"
                  ? "bg-green-100 text-green-700"
                  : "bg-gray-100 text-gray-700"
              )}>
                {video.source_type === "gdrive" ? "Drive" : video.source_type === "youtube" ? "YouTube" : video.source_type === "removable_disk" ? "Disk" : video.source_type === "local" ? "Local" : "Unknown"}
              </span>
            </div>
          </div>

          <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
            <span>{video.scene_count} {video.scene_count === 1 ? "scene" : "scenes"}</span>
            {duration > 0 && <span>{formatTimestamp(duration)}</span>}
            {video.people_count > 0 && (
              <span>{video.people_count} {video.people_count === 1 ? "person" : "people"}</span>
            )}
          </div>

          {allTags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
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

          {(video.capture_time || video.latest_ingest_time) && (
            <p className="mt-1.5 text-xs text-gray-400">
              {video.capture_time
                ? formatRelativeTime(video.capture_time)
                : `Ingested ${formatRelativeTime(video.latest_ingest_time!)}`}
            </p>
          )}
        </div>
      </div>
    </button>
  );
}
