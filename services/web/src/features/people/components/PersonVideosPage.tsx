"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useAgent } from "@/features/search/hooks/useAgent";
import { useOrgSettings } from "@/lib/orgSettings";
import {
  getPersonVideos,
  getPersonTimeline,
  unlinkPersonFromVideo,
  linkPersonToVideo,
  getPeople,
} from "@/lib/api/people";
import { getCloudPlaybackUrl, getCloudThumbnailUrl, getFaceThumbnailUrl } from "@/lib/agent";
import { cn } from "@/lib/utils";
import { PersonIcon } from "@/components/icons";
import { TimelineBar } from "./TimelineBar";
import { UnlinkVideoDialog } from "./UnlinkVideoDialog";
import { PersonPickerDropdown } from "./PersonPickerDropdown";
import type {
  PersonResponse,
  PersonVideoItem,
  PersonTimelineVideo,
} from "@/lib/types";

function BackArrowIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function LinkIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m9.86-2.504a4.5 4.5 0 00-1.242-7.244l-4.5-4.5a4.5 4.5 0 00-6.364 6.364L4.34 8.374" />
    </svg>
  );
}

function UnlinkIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.181 8.68a4.503 4.503 0 011.903 6.405m-9.768-2.782L3.56 14.06a4.5 4.5 0 006.364 6.364l3.75-3.75m-6-6l6-6m4.5 4.5l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-3.75 3.75" />
    </svg>
  );
}

export function PersonVideosPage({
  personClusterId,
}: {
  personClusterId: string;
}) {
  const { getAccessToken } = useAuth();
  const { isAvailable: agentAvailable } = useAgent();
  const router = useRouter();
  const orgSettings = useOrgSettings();

  const [person, setPerson] = useState<PersonResponse | null>(null);
  const [allPeople, setAllPeople] = useState<PersonResponse[]>([]);
  const [videos, setVideos] = useState<PersonVideoItem[]>([]);
  const [timelineVideos, setTimelineVideos] = useState<PersonTimelineVideo[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [headerImgError, setHeaderImgError] = useState(false);

  // Unlink state
  const [unlinkVideoId, setUnlinkVideoId] = useState<string | null>(null);
  const [isUnlinking, setIsUnlinking] = useState(false);

  // Link state
  const [showLinkPicker, setShowLinkPicker] = useState(false);
  const [isLinking, setIsLinking] = useState(false);
  const linkButtonRef = useRef<HTMLDivElement>(null);

  const videoRef = useRef<HTMLVideoElement>(null);

  // Fetch person + video data
  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    Promise.all([
      getPeople(getAccessToken),
      getPersonVideos(personClusterId, getAccessToken),
      getPersonTimeline(personClusterId, getAccessToken).catch(() => ({ videos: [] as PersonTimelineVideo[], person_cluster_id: personClusterId })),
    ])
      .then(([peopleRes, videosRes, timelineRes]) => {
        if (cancelled) return;
        const found = peopleRes.people.find((p) => p.person_cluster_id === personClusterId);
        setPerson(found ?? null);
        setAllPeople(peopleRes.people);
        setVideos(videosRes.videos);
        setTimelineVideos(timelineRes.videos);
        if (videosRes.videos.length > 0 && !selectedVideoId) {
          setSelectedVideoId(videosRes.videos[0].video_id);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setVideos([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [personClusterId, getAccessToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedVideo = videos.find((v) => v.video_id === selectedVideoId);
  const selectedTimeline = timelineVideos.find((t) => t.video_id === selectedVideoId);

  // Seek video to scene timestamp
  const handleSceneClick = useCallback((_videoId: string, startMs: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = startMs / 1000;
      videoRef.current.play().catch(() => {});
    }
  }, []);

  // Unlink handler
  const handleUnlink = useCallback(async () => {
    if (!unlinkVideoId) return;
    setIsUnlinking(true);
    try {
      await unlinkPersonFromVideo(personClusterId, unlinkVideoId, getAccessToken);
      setVideos((prev) => prev.filter((v) => v.video_id !== unlinkVideoId));
      setTimelineVideos((prev) => prev.filter((t) => t.video_id !== unlinkVideoId));
      if (selectedVideoId === unlinkVideoId) {
        setSelectedVideoId(videos.find((v) => v.video_id !== unlinkVideoId)?.video_id ?? null);
      }
      setUnlinkVideoId(null);
    } catch (err) {
      console.error("Failed to unlink person from video:", err);
    } finally {
      setIsUnlinking(false);
    }
  }, [personClusterId, unlinkVideoId, selectedVideoId, videos, getAccessToken]);

  // Link handler
  const handleLink = useCallback(async (targetPerson: PersonResponse) => {
    if (!selectedVideoId) return;
    setIsLinking(true);
    try {
      await linkPersonToVideo(targetPerson.person_cluster_id, selectedVideoId, getAccessToken);
      setShowLinkPicker(false);
    } catch (err) {
      console.error("Failed to link person to video:", err);
    } finally {
      setIsLinking(false);
    }
  }, [selectedVideoId, getAccessToken]);

  const playbackUrl = selectedVideoId ? getCloudPlaybackUrl(selectedVideoId) : null;
  const faceUrl = getFaceThumbnailUrl(personClusterId);
  const displayName = person?.label || "이름 없음";

  // People already linked to this video (for picker exclusion)
  const linkedPersonIds = selectedTimeline
    ? [personClusterId]
    : [personClusterId];

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-gray-200 px-6 py-4">
        <Link
          href="/settings/people"
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700"
        >
          <BackArrowIcon />
          <span>인물 설정</span>
        </Link>
        <div className="h-5 w-px bg-gray-200" />
        {!headerImgError ? (
          <img
            src={faceUrl}
            alt={displayName}
            className="h-8 w-8 flex-shrink-0 rounded-full object-cover"
            onError={() => setHeaderImgError(true)}
          />
        ) : (
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
            <PersonIcon className="h-5 w-5 text-gray-400" />
          </div>
        )}
        <div>
          <span className="text-sm font-semibold text-gray-900">{displayName}</span>
          <span className="ml-2 text-xs text-gray-400">
            동영상 {videos.length}개
          </span>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Video list */}
        <div className="w-60 flex-shrink-0 overflow-y-auto border-r border-gray-200 bg-gray-50">
          <div className="px-4 py-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
              동영상 목록 ({videos.length})
            </h3>
          </div>
          {videos.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-gray-400">
              연관된 동영상이 없습니다.
            </p>
          ) : (
            <div className="space-y-px px-2 pb-4">
              {videos.map((video) => (
                <button
                  key={video.video_id}
                  type="button"
                  onClick={() => setSelectedVideoId(video.video_id)}
                  className={cn(
                    "w-full rounded-lg px-3 py-2.5 text-left transition-colors",
                    selectedVideoId === video.video_id
                      ? "bg-indigo-50 text-indigo-700"
                      : "text-gray-700 hover:bg-gray-100",
                  )}
                >
                  <span className="line-clamp-1 text-sm font-medium">
                    {video.video_title || video.video_id}
                  </span>
                  <span className="mt-0.5 block text-xs text-gray-400">
                    {video.scene_count}개 장면
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right: Video player + actions */}
        <div className="flex flex-1 flex-col overflow-y-auto">
          {selectedVideo && playbackUrl ? (
            <div className="flex flex-1 flex-col p-6">
              {/* Video title */}
              <h2 className="mb-3 line-clamp-1 text-base font-semibold text-gray-900">
                {selectedVideo.video_title || selectedVideo.video_id}
              </h2>

              {/* Video player */}
              <div className="relative w-full overflow-hidden rounded-lg bg-black">
                <video
                  ref={videoRef}
                  key={selectedVideoId}
                  src={playbackUrl}
                  controls
                  className="h-full w-full object-contain"
                  style={{ maxHeight: "480px" }}
                />
              </div>

              {/* Timeline */}
              {selectedTimeline && selectedTimeline.scenes.length > 0 && (
                <div className="mt-3">
                  <TimelineBar
                    scenes={selectedTimeline.scenes}
                    videoId={selectedVideoId!}
                    videoTitle={selectedVideo.video_title}
                    onSceneClick={handleSceneClick}
                  />
                  <div className="mt-1 flex items-center gap-3 text-xs text-gray-400">
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-2 w-2 rounded-full bg-blue-500" />
                      인물 등장 장면
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-2 w-2 rounded-full bg-gray-200" />
                      기타 장면
                    </span>
                  </div>
                </div>
              )}

              {/* Action buttons */}
              <div className="mt-4 flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setUnlinkVideoId(selectedVideoId)}
                  className="flex items-center gap-2 rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-600 transition-colors hover:bg-red-50"
                >
                  <UnlinkIcon />
                  연결 해제
                </button>
                <div ref={linkButtonRef} className="relative">
                  <button
                    type="button"
                    onClick={() => setShowLinkPicker((prev) => !prev)}
                    className="flex items-center gap-2 rounded-lg border border-gray-200 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
                  >
                    <LinkIcon />
                    다른 인물 연결
                  </button>
                  {showLinkPicker && (
                    <PersonPickerDropdown
                      people={allPeople}
                      excludeIds={linkedPersonIds}
                      isLinking={isLinking}
                      onSelect={handleLink}
                      onClose={() => setShowLinkPicker(false)}
                    />
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-gray-400">
                {videos.length > 0
                  ? "동영상을 선택하세요"
                  : "이 인물이 등장하는 동영상이 없습니다"}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Unlink confirmation dialog */}
      <UnlinkVideoDialog
        isOpen={unlinkVideoId !== null}
        personLabel={person?.label ?? null}
        videoTitle={videos.find((v) => v.video_id === unlinkVideoId)?.video_title ?? null}
        isUnlinking={isUnlinking}
        onCancel={() => setUnlinkVideoId(null)}
        onConfirm={handleUnlink}
      />
    </div>
  );
}
