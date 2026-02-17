"use client";

import { useState } from "react";
import { getAgentThumbnailUrl, getCloudThumbnailUrl } from "@/lib/agent";
import { cn } from "@/lib/utils";

type FallbackStage = "cloud" | "agent" | "placeholder";

interface SceneThumbnailProps {
  videoId: string;
  sceneId?: string;
  agentAvailable: boolean;
  className?: string;
}

const VideoIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    fill="none"
    viewBox="0 0 24 24"
    stroke="currentColor"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
      d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
    />
  </svg>
);

export function SceneThumbnail({
  videoId,
  sceneId,
  agentAvailable,
  className,
}: SceneThumbnailProps) {
  const canTryCloud = !!sceneId;

  const initialStage: FallbackStage = canTryCloud
    ? "cloud"
    : agentAvailable
      ? "agent"
      : "placeholder";

  const [stage, setStage] = useState<FallbackStage>(initialStage);

  const handleError = () => {
    if (stage === "cloud" && agentAvailable) {
      setStage("agent");
    } else {
      setStage("placeholder");
    }
  };

  const src =
    stage === "cloud" && sceneId
      ? getCloudThumbnailUrl(videoId, sceneId)
      : stage === "agent"
        ? getAgentThumbnailUrl(videoId, sceneId)
        : null;

  return (
    <div className={cn("bg-gray-200 overflow-hidden", className)}>
      {src ? (
        <img
          src={src}
          alt=""
          className="w-full h-full object-cover"
          onError={handleError}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-gray-400">
          <VideoIcon className="w-8 h-8" />
        </div>
      )}
    </div>
  );
}
