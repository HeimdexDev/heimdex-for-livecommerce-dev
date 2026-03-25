"use client";

import { useEffect } from "react";
import type { VideoSummary, VideoScene } from "@/lib/types";
import { formatTimestamp } from "@/lib/api/utils";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { ShortsPlanPanel } from "./ShortsPlanPanel";
import { OpenInDriveButton } from "@/components/OpenInDriveButton";
import { useOrgSettings } from "@/lib/orgSettings";
import { getDrawerHeroClass, getSmallThumbnailClass, type ThumbnailAspectRatio } from "@/lib/thumbnailUtils";
import { cn } from "@/lib/utils";
import { FEATURES } from "@/lib/feature-flags";

interface VideoDetailDrawerProps {
  video: VideoSummary | null;
  scenes: VideoScene[];
  totalScenes: number;
  isOpen: boolean;
  isLoading: boolean;
  onClose: () => void;
  agentAvailable: boolean;
}

export function VideoDetailDrawer({
  video,
  scenes,
  totalScenes,
  isOpen,
  isLoading,
  onClose,
  agentAvailable,
}: VideoDetailDrawerProps) {
  const { settings } = useOrgSettings();
  const aspectRatio = settings.thumbnail_aspect_ratio as ThumbnailAspectRatio;

  useEffect(() => {
    if (!isOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [isOpen, onClose]);

  if (!isOpen || !video) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        role="presentation"
      />

      <div className="relative w-full max-w-lg bg-white shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between z-10">
          <div className="min-w-0 flex items-center gap-2">
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-gray-900 truncate" title={video.video_title || video.video_id}>
                {video.video_title || video.video_id}
              </h2>
              <p className="text-xs text-gray-500">
                {video.library_name || "Unknown library"}
              </p>
            </div>
            <OpenInDriveButton
              sourceType={video.source_type ?? "local"}
              webViewLink={video.web_view_link}
            />
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
            aria-label="Close"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="px-6 pt-4">
          <SceneThumbnail
            videoId={video.video_id}
            sceneId={video.source_type === "gdrive" ? `${video.video_id}_scene_000` : undefined}
            agentAvailable={agentAvailable}
            className={cn("w-full rounded-lg", getDrawerHeroClass(aspectRatio))}
          />
        </div>

        <div className="px-6 py-4 border-b border-gray-100">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span className="text-gray-500">Scenes</span>
              <p className="font-medium text-gray-900">{video.scene_count}</p>
            </div>
            <div>
              <span className="text-gray-500">Source</span>
              <p className="font-medium text-gray-900">
                {video.source_type === "gdrive" ? "Google Drive" : video.source_type === "removable_disk" ? "Removable Disk" : "Local"}
              </p>
            </div>
            {video.source_path && (
              <div className="col-span-2">
                <span className="text-gray-500">Library Path</span>
                <p className="font-medium text-gray-900 truncate" title={video.source_path}>
                  {video.source_path}
                </p>
              </div>
            )}
            {video.people_count > 0 && (
              <div>
                <span className="text-gray-500">People</span>
                <p className="font-medium text-gray-900">{video.people_count}</p>
              </div>
            )}
            {(video.capture_time || video.latest_ingest_time) && (
              <div>
                <span className="text-gray-500">{video.capture_time ? "업로드일" : "등록일"}</span>
                <p className="font-medium text-gray-900">
                  {new Date(video.capture_time || video.latest_ingest_time!).toLocaleString("ko-KR")}
                </p>
              </div>
            )}
          </div>
        </div>

        <div className="px-6 py-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            Scenes ({totalScenes})
          </h3>

          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="animate-pulse">
                  <div className="h-3 w-24 bg-gray-200 rounded" />
                  <div className="h-3 w-full bg-gray-200 rounded mt-2" />
                  <div className="h-3 w-2/3 bg-gray-200 rounded mt-1" />
                </div>
              ))}
            </div>
          ) : scenes.length === 0 ? (
            <p className="text-sm text-gray-500">No scenes found.</p>
          ) : (
            <div className="space-y-3">
              {scenes.map((scene) => (
                <div
                  key={scene.scene_id}
                  className="p-3 rounded-lg border border-gray-100 hover:border-gray-200 transition-colors"
                >
                  <div className="flex gap-3">
                    {video && (
                      <SceneThumbnail
                        videoId={video.video_id}
                        sceneId={scene.scene_id}
                        agentAvailable={agentAvailable}
                        className={cn("flex-shrink-0 rounded", getSmallThumbnailClass(aspectRatio))}
                      />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between text-xs text-gray-500">
                        <span className="font-mono">
                          {formatTimestamp(scene.start_ms)} - {formatTimestamp(scene.end_ms)}
                        </span>
                        {scene.speech_segment_count > 0 && (
                          <span>{scene.speech_segment_count} segments</span>
                        )}
                      </div>
                      {scene.transcript_raw && (
                        <p className="mt-1 text-sm text-gray-700 line-clamp-2">
                          {scene.transcript_raw.slice(0, 150)}
                          {scene.transcript_raw.length > 150 ? "..." : ""}
                        </p>
                      )}
                      {FEATURES.TAGS_ENABLED && (scene.keyword_tags.length > 0 || scene.product_tags.length > 0) && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {[...scene.keyword_tags, ...scene.product_tags].slice(0, 5).map((tag) => (
                            <span
                              key={tag}
                              className="inline-block px-1.5 py-0.5 text-xs bg-blue-50 text-blue-700 rounded"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <ShortsPlanPanel
          videoId={video.video_id}
          videoTitle={video.video_title}
          agentAvailable={agentAvailable}
        />
      </div>
    </div>
  );
}
