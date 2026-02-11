"use client";

import { useVideos } from "../hooks/useVideos";
import { StatsBar } from "./StatsBar";
import { VideoFilterPanel } from "./VideoFilterPanel";
import { VideoList } from "./VideoList";
import { VideoDetailDrawer } from "./VideoDetailDrawer";

export function VideosContainer() {
  const {
    videos,
    stats,
    facets,
    filters,
    isLoading,
    isLoadingMore,
    isLoadingScenes,
    error,
    nextCursor,
    total,
    selectedVideoId,
    selectedVideoScenes,
    selectedVideoTotal,
    setFilters,
    loadMore,
    selectVideo,
    closeDrawer,
  } = useVideos();

  const selectedVideo = selectedVideoId
    ? videos.find((v) => v.video_id === selectedVideoId) ?? null
    : null;

  return (
    <div className="min-h-screen">
      <main className="max-w-7xl mx-auto px-4 py-6">
        <StatsBar stats={stats} isLoading={isLoading && !stats} />

        {error && (
          <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            <p className="font-medium">Error</p>
            <p className="text-sm">{error}</p>
          </div>
        )}

        <div className="flex gap-6 mt-6">
          <aside className="w-64 flex-shrink-0">
            <div className="card p-4 sticky top-4">
              <VideoFilterPanel
                facets={facets}
                filters={filters}
                onChange={setFilters}
              />
            </div>
          </aside>

          <div className="flex-1 min-w-0">
            <VideoList
              videos={videos}
              isLoading={isLoading}
              isLoadingMore={isLoadingMore}
              hasMore={nextCursor !== null}
              total={total}
              onSelect={selectVideo}
              onLoadMore={loadMore}
            />
          </div>
        </div>
      </main>

      <VideoDetailDrawer
        video={selectedVideo}
        scenes={selectedVideoScenes}
        totalScenes={selectedVideoTotal}
        isOpen={selectedVideoId !== null}
        isLoading={isLoadingScenes}
        onClose={closeDrawer}
      />

      <footer className="border-t border-gray-200 mt-12 py-6">
        <div className="max-w-7xl mx-auto px-4 text-center text-sm text-gray-500">
          <p>Heimdex v0.1.0 - Development Build</p>
          <p className="mt-1">
            Video playback requires the Heimdex agent running on your machine.
          </p>
        </div>
      </footer>
    </div>
  );
}
