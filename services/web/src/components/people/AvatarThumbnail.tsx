"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { getCloudThumbnailUrl, getFaceThumbnailUrl } from "@/lib/agent";
import { PersonIcon } from "@/components/icons";
import type { PersonResponse } from "@/lib/types";

/** Thumbnail content shared between PersonAvatar and DragOverlay */
export function AvatarThumbnail({
  person,
  agentAvailable,
  className,
}: {
  person: PersonResponse;
  agentAvailable: boolean;
  className?: string;
}) {
  const [imgError, setImgError] = useState(false);
  const faceThumbnailUrl = getFaceThumbnailUrl(person.person_cluster_id);
  const sceneThumbnailUrl =
    person.representative_video_id && person.representative_scene_id
      ? getCloudThumbnailUrl(person.representative_video_id, person.representative_scene_id)
      : null;
  const [useFallback, setUseFallback] = useState(false);
  const thumbnailUrl = !useFallback ? faceThumbnailUrl : sceneThumbnailUrl;

  return (
    <div
      className={cn(
        "flex h-24 w-24 items-center justify-center overflow-hidden rounded-2xl bg-gray-100 transition-all group-hover:brightness-90",
        className,
      )}
    >
      {thumbnailUrl && !imgError ? (
        <img
          src={thumbnailUrl}
          alt={person.label ?? "인물"}
          className="h-full w-full object-cover"
          onError={() => {
            if (!useFallback && sceneThumbnailUrl) {
              setUseFallback(true);
            } else {
              setImgError(true);
            }
          }}
        />
      ) : (
        <div className="relative flex h-full w-full items-center justify-center">
          <PersonIcon className="h-12 w-12 text-gray-400" />
          {!agentAvailable && (
            <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-gray-500/80 px-1.5 py-0.5 text-[8px] font-medium leading-tight text-white">
              오프라인
            </span>
          )}
        </div>
      )}
    </div>
  );
}
