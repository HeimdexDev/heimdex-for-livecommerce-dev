"use client";

import type { VideoSummary } from "@/lib/types";
import { VideoCard } from "./VideoCard";

interface VideoListProps {
  videos: VideoSummary[];
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  total: number;
  onSelect: (videoId: string) => void;
  onLoadMore: () => void;
  agentAvailable: boolean;
}

function SkeletonCard() {
  return (
    <div className="card p-4 animate-pulse">
      <div className="h-4 w-3/4 bg-gray-200 rounded" />
      <div className="h-3 w-1/3 bg-gray-200 rounded mt-2" />
      <div className="flex gap-4 mt-3">
        <div className="h-3 w-16 bg-gray-200 rounded" />
        <div className="h-3 w-12 bg-gray-200 rounded" />
      </div>
    </div>
  );
}

export function VideoList({
  videos,
  isLoading,
  isLoadingMore,
  hasMore,
  total,
  onSelect,
  onLoadMore,
  agentAvailable,
}: VideoListProps) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    );
  }

  if (videos.length === 0) {
    return (
      <div className="text-center py-16 text-gray-500">
        <svg
          className="w-16 h-16 mx-auto mb-4 text-gray-300"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
          />
        </svg>
        <p className="text-lg font-medium">No videos ingested yet</p>
        <p className="text-sm mt-1">
          Videos will appear here once the Heimdex agent processes them.
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm text-gray-500 mb-3">
        Showing {videos.length} of {total} {total === 1 ? "video" : "videos"}
      </p>

      <div className="space-y-3">
        {videos.map((video) => (
          <VideoCard key={video.video_id} video={video} onSelect={onSelect} agentAvailable={agentAvailable} />
        ))}
      </div>

      {hasMore && (
        <div className="mt-4 text-center">
          <button
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="px-6 py-2 text-sm font-medium text-primary-600 hover:text-primary-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {isLoadingMore ? "Loading..." : "Load More"}
          </button>
        </div>
      )}
    </div>
  );
}
