"use client";

import { useRef, useEffect, useState } from "react";
import {
  getCloudPlaybackUrl,
  getAgentPlaybackUrl,
  getCloudThumbnailUrl,
} from "@/lib/agent";
import type { SceneResult } from "@/lib/types";

interface ScenePreviewPlayerProps {
  scene: SceneResult;
}

function formatMs(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function ScenePreviewPlayer({ scene }: ScenePreviewPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState(false);

  const isCloud = scene.source_type === "gdrive";
  const playbackUrl = isCloud
    ? getCloudPlaybackUrl(scene.video_id, scene.start_ms)
    : getAgentPlaybackUrl(scene.video_id, scene.start_ms);
  const posterUrl = isCloud
    ? getCloudThumbnailUrl(scene.video_id, scene.scene_id)
    : undefined;

  const durationSec = Math.round((scene.end_ms - scene.start_ms) / 1000);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    setError(false);

    const doSeek = () => {
      video.currentTime = scene.start_ms / 1000;
      video.play().catch(() => {});
    };

    if (video.readyState >= 1) {
      doSeek();
    } else {
      video.addEventListener("loadedmetadata", doSeek, { once: true });
      return () => video.removeEventListener("loadedmetadata", doSeek);
    }
  }, [scene.start_ms]);

  return (
    <div>
      <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
        {error ? (
          <div className="flex h-full items-center justify-center text-xs text-gray-400">
            재생할 수 없습니다
          </div>
        ) : (
          <video
            ref={videoRef}
            src={playbackUrl}
            poster={posterUrl}
            controls
            playsInline
            onError={() => setError(true)}
            className="h-full w-full object-contain"
          />
        )}
      </div>
      <div className="mt-2 px-1">
        <p className="line-clamp-1 text-xs font-medium text-gray-700">
          {scene.video_title || scene.video_id}
        </p>
        <p className="text-[10px] text-gray-500">
          {formatMs(scene.start_ms)} - {formatMs(scene.end_ms)} ({durationSec}s)
        </p>
      </div>
    </div>
  );
}

export function ScenePreviewEmpty() {
  return (
    <div className="aspect-video w-full overflow-hidden rounded-lg border border-dashed border-gray-300 bg-gray-100">
      <div className="flex h-full flex-col items-center justify-center gap-1">
        <svg
          className="h-8 w-8 text-gray-300"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z"
          />
        </svg>
        <span className="text-[10px] text-gray-400">장면을 클릭하여 미리보기</span>
      </div>
    </div>
  );
}
