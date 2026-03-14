"use client";

import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { usePeople } from "../hooks/usePeople";
import { useAuth } from "@/lib/auth";
import { useAgent } from "@/features/search/hooks/useAgent";
import { getPersonTimeline, getPersonVideos, getVideoExclusions, saveVideoExclusions } from "@/lib/api/people";
import { getCloudThumbnailUrl, getFaceThumbnailUrl } from "@/lib/agent";
import type { PersonResponse, PersonTimelineVideo, PersonVideoItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PersonIcon } from "@/components/icons";
import { ScenePreviewTooltip } from "@/components/ScenePreviewTooltip";
import { DeletePersonDialog } from "./DeletePersonDialog";
import { MergeConfirmDialog } from "./MergeConfirmDialog";
import { TimelineBar } from "./TimelineBar";

/** Format ISO 8601 timestamp to Korean relative time string */
function formatRelativeTime(isoTimestamp: string | null | undefined): string | null {
  if (!isoTimestamp) return null;
  const diffMs = Date.now() - new Date(isoTimestamp).getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "방금 전";
  if (diffMins < 60) return `${diffMins}분 전`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}시간 전`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}일 전`;
  const diffMonths = Math.floor(diffDays / 30);
  return `${diffMonths}개월 전`;
}

function PencilIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487z" />
    </svg>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
  );
}

function VideoIcon() {
  return (
    <svg className="h-16 w-16 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg className="h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
  );
}

function BackArrowIcon() {
  return (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
      <path
        fillRule="evenodd"
        d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z"
        clipRule="evenodd"
      />
    </svg>
  );
}

function EllipsisVerticalIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
    </svg>
  );
}

function EyeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  );
}

function EyeSlashIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
    </svg>
  );
}

/** Thumbnail content shared between PersonAvatar and DragOverlay */
function AvatarThumbnail({
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
        "flex h-20 w-20 items-center justify-center overflow-hidden rounded-full bg-gray-100 transition-all",
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
          <PersonIcon className="h-10 w-10 text-gray-400" />
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

function PersonAvatar({
  person,
  isSelected,
  onToggle,
  onDelete,
  onRename,
  agentAvailable,
  isDragActive,
}: {
  person: PersonResponse;
  isSelected: boolean;
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
  onRename?: () => void;
  agentAvailable: boolean;
  isDragActive: boolean;
}) {
  const {
    attributes,
    listeners,
    setNodeRef: setDragRef,
    isDragging,
  } = useDraggable({
    id: `person-${person.person_cluster_id}`,
    data: { person },
  });

  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `person-${person.person_cluster_id}`,
    data: { person },
  });

  // Combine drag and drop refs
  const setNodeRef = useCallback(
    (node: HTMLElement | null) => {
      setDragRef(node);
      setDropRef(node);
    },
    [setDragRef, setDropRef],
  );

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [menuOpen]);

  return (
    <ScenePreviewTooltip
      videoId={person.representative_video_id}
      sceneId={person.representative_scene_id}
      label={person.label}
      badge={[`${person.face_count}개 장면`, formatRelativeTime(person.last_seen_scene_time)].filter(Boolean).join(" · ")}
      disabled={isDragging || isDragActive || isOver}
    >
      <div
        ref={setNodeRef}
        className={cn(
          "group relative flex flex-col items-center gap-1",
          isDragging && "opacity-30",
        )}
        {...attributes}
        {...listeners}
      >
        <button
          type="button"
          onClick={() => {
            if (!isDragActive) onToggle(person.person_cluster_id);
          }}
          className="flex flex-col items-center"
        >
          <AvatarThumbnail
            person={person}
            agentAvailable={agentAvailable}
            className={cn(
              isSelected && "ring-2 ring-indigo-500 ring-offset-2",
              !isSelected && !isOver && "hover:bg-gray-200",
              isOver && "ring-2 ring-indigo-500 scale-105 bg-indigo-50",
            )}
          />
        </button>
        <div className="absolute -right-1 -top-1 z-10">
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setMenuOpen((prev) => !prev); }}
            className="hidden group-hover:flex items-center justify-center w-6 h-6 rounded-full bg-white shadow-md border border-gray-200 text-gray-600 hover:text-gray-900"
          >
            <EllipsisVerticalIcon className="w-4 h-4" />
          </button>
          {menuOpen && (
            <div
              ref={menuRef}
              className="absolute right-0 top-7 z-40 w-36 rounded-lg border border-gray-100 bg-white shadow-lg py-1"
              onPointerDown={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onRename?.(); }}
                className="w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
              >
                이름 변경
              </button>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onDelete(person.person_cluster_id); }}
                className="w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
              >
                삭제
              </button>
            </div>
          )}
        </div>
        {person.label && (
          <span className="max-w-[80px] truncate text-xs text-gray-600">
            {person.label}
          </span>
        )}
      </div>
    </ScenePreviewTooltip>
  );
}

function SelectedPersonCard({
  person,
  onRename,
  isRenaming,
  getToken,
  refreshTrigger,
}: {
  person: PersonResponse;
  onRename: (id: string, label: string | null) => Promise<void>;
  isRenaming: boolean;
  getToken: () => Promise<string | null>;
  /** Monotonic counter — increment to force video list re-fetch. */
  refreshTrigger: number;
}) {
  const INITIAL_VIDEO_COUNT = 5;
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(person.label ?? "");
  const [videoFiles, setVideoFiles] = useState<PersonVideoItem[]>([]);
  const [loadingVideos, setLoadingVideos] = useState(true);
  const [headerImgError, setHeaderImgError] = useState(false);
  const [headerUseFallback, setHeaderUseFallback] = useState(false);
  const [excludedVideoIds, setExcludedVideoIds] = useState<Set<string>>(new Set());
  const [timelineVideos, setTimelineVideos] = useState<PersonTimelineVideo[]>([]);
  const [showAllVideos, setShowAllVideos] = useState(false);
  const router = useRouter();
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const inputRef = useRef<HTMLInputElement>(null);
  const headerFaceUrl = getFaceThumbnailUrl(person.person_cluster_id);
  const headerSceneUrl =
    person.representative_video_id && person.representative_scene_id
      ? getCloudThumbnailUrl(person.representative_video_id, person.representative_scene_id)
      : null;
  const headerThumbnailUrl = !headerUseFallback ? headerFaceUrl : headerSceneUrl;

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  useEffect(() => {
    setShowAllVideos(false);
  }, [person.person_cluster_id]);

  useEffect(() => {
    let cancelled = false;
    setLoadingVideos(true);

    Promise.all([
      getPersonVideos(person.person_cluster_id, getToken),
      getVideoExclusions(person.person_cluster_id, getToken),
      getPersonTimeline(person.person_cluster_id, getToken).catch(() => ({ videos: [] })),
    ])
      .then(([videosRes, exclusionsRes, timelineRes]) => {
        if (cancelled) return;
        setVideoFiles(videosRes.videos);
        setExcludedVideoIds(new Set(exclusionsRes.excluded_video_ids));
        setTimelineVideos(timelineRes.videos);
      })
      .catch(() => {
        if (!cancelled) setVideoFiles([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingVideos(false);
      });

    return () => {
      cancelled = true;
    };
  }, [person.person_cluster_id, getToken, refreshTrigger]);

  const toggleVideo = useCallback(
    (videoId: string) => {
      setExcludedVideoIds((prev) => {
        const next = new Set(prev);
        if (next.has(videoId)) next.delete(videoId);
        else next.add(videoId);

        if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
        saveTimeoutRef.current = setTimeout(() => {
          saveVideoExclusions(
            person.person_cluster_id,
            Array.from(next),
            getToken,
          ).catch((err) => console.error("Failed to save video exclusions:", err));
        }, 500);

        return next;
      });
    },
    [person.person_cluster_id, getToken],
  );

  useEffect(
    () => () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    },
    [],
  );

  const handleSave = async () => {
    const trimmed = editValue.trim();
    const newLabel = trimmed || null;
    if (newLabel !== person.label) {
      await onRename(person.person_cluster_id, newLabel);
    }
    setIsEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSave();
    else if (e.key === "Escape") {
      setEditValue(person.label ?? "");
      setIsEditing(false);
    }
  };

  const displayName = person.label || "이름 추가";
  const hasLabel = !!person.label;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center gap-2">
        {headerThumbnailUrl && !headerImgError ? (
          <img
            src={headerThumbnailUrl}
            alt={person.label ?? "인물"}
            className="h-8 w-8 flex-shrink-0 rounded-full object-cover"
            onError={() => {
              if (!headerUseFallback && headerSceneUrl) {
                setHeaderUseFallback(true);
              } else {
                setHeaderImgError(true);
              }
            }}
          />
        ) : (
          <div className="relative flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
            <PersonIcon className="h-5 w-5 text-gray-400" />
          </div>
        )}
        {isEditing ? (
          <input
            ref={inputRef}
            type="text"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={handleSave}
            onKeyDown={handleKeyDown}
            disabled={isRenaming}
            maxLength={100}
            placeholder="이름 입력..."
            className="flex-1 rounded border border-indigo-300 px-2 py-0.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
         ) : (
           <div className="flex flex-1 items-center gap-1.5">
             <button
               type="button"
               onClick={() => {
                 setEditValue(person.label ?? "");
                 setIsEditing(true);
               }}
               className="flex flex-1 items-center gap-1.5"
             >
               <span className={cn("text-sm font-medium", hasLabel ? "text-gray-900" : "text-indigo-500")}>
                 {displayName}
               </span>
               <PencilIcon />
             </button>
             {person.last_seen_scene_time && (
               <span className="text-xs text-gray-400">{formatRelativeTime(person.last_seen_scene_time)}</span>
             )}
           </div>
         )}
      </div>

      <div className="space-y-1">
        {loadingVideos ? (
          <div className="flex items-center justify-center py-4">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-300 border-t-indigo-500" />
          </div>
        ) : videoFiles.length === 0 ? (
          <p className="py-2 text-xs text-gray-400">연관된 영상이 없습니다.</p>
        ) : (
          <>
            <div className={showAllVideos && videoFiles.length > INITIAL_VIDEO_COUNT ? "max-h-[400px] overflow-y-auto" : ""}>
               {(showAllVideos ? videoFiles : videoFiles.slice(0, INITIAL_VIDEO_COUNT)).map((video) => {
                 const isExcluded = excludedVideoIds.has(video.video_id);
                 const timeline = timelineVideos.find((t) => t.video_id === video.video_id);
                 return (
                   <div key={video.video_id} className="space-y-0.5 px-1 py-1">
                     <div className="flex w-full items-center justify-between rounded hover:bg-gray-50 py-1">
                       <span className={cn("truncate text-sm", isExcluded ? "line-through text-gray-400" : "text-gray-700")}>
                         {video.video_title || video.video_id}
                       </span>
                       <button
                         type="button"
                         onClick={() => toggleVideo(video.video_id)}
                         aria-label={isExcluded ? "영상 포함하기" : "영상 제외하기"}
                         className="p-1 text-gray-400 hover:text-gray-600 flex-shrink-0"
                       >
                         {isExcluded ? <EyeSlashIcon className="w-4 h-4" /> : <EyeIcon className="w-4 h-4" />}
                       </button>
                     </div>
                     {timeline && timeline.scenes.length > 0 && (
                       <TimelineBar
                         scenes={timeline.scenes}
                         videoId={video.video_id}
                         videoTitle={video.video_title}
                         onSceneClick={(vid, ms) => router.push(`/videos/${vid}?t=${ms}`)}
                       />
                     )}
                   </div>
                 );
               })}
            </div>
            {videoFiles.length > INITIAL_VIDEO_COUNT && !showAllVideos && (
              <button
                onClick={() => setShowAllVideos(true)}
                className="mt-2 w-full py-1 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-md hover:bg-gray-50 transition-colors"
              >
                더보기 ({videoFiles.length - INITIAL_VIDEO_COUNT}개 더)
              </button>
            )}
            {showAllVideos && (
              <button
                onClick={() => setShowAllVideos(false)}
                className="mt-2 w-full py-1 text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-md hover:bg-gray-50 transition-colors"
              >
                접기
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

interface PeopleGridPaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

function PeopleGridPagination({
  currentPage,
  totalPages,
  onPageChange,
}: PeopleGridPaginationProps) {
  if (totalPages <= 1) return null;

  const pages = useMemo(() => {
    const result: (number | "ellipsis")[] = [];
    const maxVisible = 5;

    if (totalPages <= maxVisible + 2) {
      for (let i = 1; i <= totalPages; i++) result.push(i);
    } else {
      result.push(1);

      let start = Math.max(2, currentPage - 1);
      let end = Math.min(totalPages - 1, currentPage + 1);

      if (currentPage <= 3) {
        start = 2;
        end = Math.min(maxVisible, totalPages - 1);
      } else if (currentPage >= totalPages - 2) {
        start = Math.max(2, totalPages - maxVisible + 1);
        end = totalPages - 1;
      }

      if (start > 2) result.push("ellipsis");
      for (let i = start; i <= end; i++) result.push(i);
      if (end < totalPages - 1) result.push("ellipsis");

      result.push(totalPages);
    }
    return result;
  }, [currentPage, totalPages]);

  const btnBase =
    "inline-flex h-8 w-8 items-center justify-center rounded text-sm transition-colors";

  return (
    <nav className="mt-6 flex items-center justify-center gap-1">
      <button
        type="button"
        disabled={currentPage === 1}
        onClick={() => onPageChange(1)}
        className={cn(
          btnBase,
          currentPage === 1
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="처음"
      >
        &laquo;
      </button>
      <button
        type="button"
        disabled={currentPage === 1}
        onClick={() => onPageChange(currentPage - 1)}
        className={cn(
          btnBase,
          currentPage === 1
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="이전"
      >
        &lsaquo;
      </button>

      {pages.map((p, i) =>
        p === "ellipsis" ? (
          <span
            key={`ell-${i}`}
            className="inline-flex h-8 w-8 items-center justify-center text-sm text-gray-400"
          >
            &hellip;
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => onPageChange(p)}
            className={cn(
              btnBase,
              currentPage === p
                ? "bg-indigo-500 font-medium text-white"
                : "text-gray-600 hover:bg-gray-100",
            )}
          >
            {p}
          </button>
        ),
      )}

      <button
        type="button"
        disabled={currentPage === totalPages}
        onClick={() => onPageChange(currentPage + 1)}
        className={cn(
          btnBase,
          currentPage === totalPages
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="다음"
      >
        &rsaquo;
      </button>
      <button
        type="button"
        disabled={currentPage === totalPages}
        onClick={() => onPageChange(totalPages)}
        className={cn(
          btnBase,
          currentPage === totalPages
            ? "cursor-not-allowed text-gray-300"
            : "text-gray-500 hover:bg-gray-100",
        )}
        aria-label="마지막"
      >
        &raquo;
      </button>
    </nav>
  );
}

export function PeopleSettings() {
  const {
    people,
    isLoading,
    error,
    renamePerson,
    isRenaming,
    excludedIds,
    toggleExclude,
    isSavingExcludes,
    selectedIds,
    toggleSelection,
    deletePerson,
    isDeleting,
    mergePeople,
    isMerging,
  } = usePeople();
  const { getAccessToken } = useAuth();
  const { isAvailable: agentAvailable } = useAgent();
  const [searchQuery, setSearchQuery] = useState("");
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);

  // DnD merge state
  const [activeDragPerson, setActiveDragPerson] = useState<PersonResponse | null>(null);
  const [mergeSource, setMergeSource] = useState<PersonResponse | null>(null);
  const [mergeTarget, setMergeTarget] = useState<PersonResponse | null>(null);
  // Incremented after each successful merge to force SelectedPersonCard
  // to refetch its video list (the person_cluster_id dep alone won't change).
  const [videoRefreshKey, setVideoRefreshKey] = useState(0);

  // Require 8px movement before drag starts (prevents accidental drags on click)
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    }),
  );

  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 24;

  const filteredPeople = useMemo(() => {
    if (!searchQuery.trim()) return people;
    const q = searchQuery.trim().toLowerCase();
    return people.filter(
      (p) =>
        p.label?.toLowerCase().includes(q) ||
        p.person_cluster_id.toLowerCase().includes(q),
    );
  }, [people, searchQuery]);

  const totalPages = Math.ceil(filteredPeople.length / PAGE_SIZE);
  const paginatedPeople = filteredPeople.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  );

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(filteredPeople.length / PAGE_SIZE));
    if (currentPage > maxPage) setCurrentPage(maxPage);
  }, [filteredPeople.length, currentPage]);

  const selectedPeople = useMemo(
    () => people.filter((p) => selectedIds.has(p.person_cluster_id)),
    [people, selectedIds],
  );

  const hasPeople = people.length > 0;

  const handleDragStart = useCallback(
    (event: DragStartEvent) => {
      const person = event.active.data.current?.person as PersonResponse | undefined;
      if (person) {
        setActiveDragPerson(person);
      }
    },
    [],
  );

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      setActiveDragPerson(null);

      const { active, over } = event;
      if (!over || active.id === over.id) return;

      const sourcePerson = active.data.current?.person as PersonResponse | undefined;
      const targetPerson = over.data.current?.person as PersonResponse | undefined;

      if (sourcePerson && targetPerson) {
        setMergeSource(sourcePerson);
        setMergeTarget(targetPerson);
      }
    },
    [],
  );

  const handleDragCancel = useCallback(() => {
    setActiveDragPerson(null);
  }, []);

  const handleMergeConfirm = useCallback(
    async (keepLabel?: string | null) => {
      if (!mergeSource || !mergeTarget) return;
      await mergePeople({
        source_cluster_ids: [mergeSource.person_cluster_id],
        target_cluster_id: mergeTarget.person_cluster_id,
        keep_label: keepLabel,
      });
      setMergeSource(null);
      setMergeTarget(null);
      // Bump refresh key so SelectedPersonCard re-fetches video list
      // for the surviving target cluster (now includes merged scenes).
      setVideoRefreshKey((k) => k + 1);
    },
    [mergeSource, mergeTarget, mergePeople],
  );

  const handleMergeCancel = useCallback(() => {
    setMergeSource(null);
    setMergeTarget(null);
  }, []);

  return (
    <div>
      <div className="mb-6 flex items-center gap-3 text-sm text-gray-500">
        <Link href="/" className="rounded-full p-1 hover:bg-gray-200">
          <BackArrowIcon />
        </Link>
        <Link href="/" className="hover:text-gray-700">전체 아카이브 검색</Link>
        <span>{">"}</span>
        <span className="text-gray-700">인물 라벨 관리</span>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="flex min-h-[400px] items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      ) : (
        <div className="flex gap-6">
          <div className="w-[340px] flex-shrink-0">
            <h2 className="mb-4 text-lg font-bold text-gray-900">
              제외할 영상 선택
            </h2>
            <div className="min-h-[300px] rounded-xl bg-white p-4 shadow-sm">
              {selectedPeople.length === 0 ? (
                <div className="flex min-h-[200px] items-center justify-center">
                  <p className="text-sm text-gray-400">선택된 인물이 없습니다.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {selectedPeople.map((person) => (
                    <SelectedPersonCard
                      key={person.person_cluster_id}
                      person={person}
                      onRename={renamePerson}
                      isRenaming={isRenaming}
                      getToken={getAccessToken}
                      refreshTrigger={videoRefreshKey}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex-1">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-gray-900">인물 검색</h2>
              <span className="text-sm text-gray-500">
                {selectedIds.size}명 선택됨
              </span>
            </div>

            <div className="rounded-xl bg-white p-4 shadow-sm">
              <form
                onSubmit={(e) => e.preventDefault()}
                className="mb-4 flex items-center gap-3"
              >
                <div className="relative flex-1">
                  <SearchIcon className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={
                      hasPeople
                        ? "인물 이름을 검색해주세요."
                        : "파일 추가 완료 후에 인물을 찾아보세요."
                    }
                    className="w-full rounded-lg border border-gray-200 py-2.5 pl-10 pr-4 text-sm placeholder:text-gray-400 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                  />
                </div>
                <button
                  type="submit"
                  className={cn(
                    "rounded-lg px-5 py-2.5 text-sm font-medium text-white transition-colors",
                    hasPeople
                      ? "bg-indigo-500 hover:bg-indigo-600"
                      : "cursor-not-allowed bg-gray-300",
                  )}
                  disabled={!hasPeople}
                >
                  검색
                </button>
              </form>

              {!hasPeople ? (
                <div className="flex flex-col items-center py-16">
                  <VideoIcon />
                  <h3 className="mt-6 text-lg font-bold text-gray-900">
                    인물을 찾을 수 없습니다.
                  </h3>
                  <p className="mt-2 text-sm text-gray-500">
                    파일 동기화부터 진행해주세요.
                  </p>
                  <Link
                    href="/sync"
                    className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-indigo-500 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-indigo-600"
                  >
                    파일 동기화로 이동
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                    </svg>
                  </Link>
                </div>
              ) : (
                <DndContext
                  sensors={sensors}
                  onDragStart={handleDragStart}
                  onDragEnd={handleDragEnd}
                  onDragCancel={handleDragCancel}
                >
                  <div className="grid grid-cols-5 gap-4">
                    {paginatedPeople.map((person) => (
                      <PersonAvatar
                        key={person.person_cluster_id}
                        person={person}
                        isSelected={selectedIds.has(person.person_cluster_id)}
                        onToggle={toggleSelection}
                        onDelete={setDeleteTargetId}
                        onRename={() => toggleSelection(person.person_cluster_id)}
                        agentAvailable={agentAvailable}
                        isDragActive={activeDragPerson !== null}
                      />
                    ))}
                  </div>
                  {totalPages > 1 && (
                    <PeopleGridPagination
                      currentPage={currentPage}
                      totalPages={totalPages}
                      onPageChange={setCurrentPage}
                    />
                  )}
                  <DragOverlay dropAnimation={null}>
                    {activeDragPerson ? (
                      <div className="flex flex-col items-center gap-1 opacity-80">
                        <AvatarThumbnail
                          person={activeDragPerson}
                          agentAvailable={agentAvailable}
                          className="ring-2 ring-indigo-400 shadow-lg"
                        />
                        {activeDragPerson.label && (
                          <span className="max-w-[80px] truncate text-xs text-gray-600">
                            {activeDragPerson.label}
                          </span>
                        )}
                      </div>
                    ) : null}
                  </DragOverlay>
                </DndContext>
              )}
            </div>
          </div>
        </div>
      )}
      <DeletePersonDialog
        isOpen={deleteTargetId !== null}
        personLabel={
          people.find((p) => p.person_cluster_id === deleteTargetId)?.label ?? null
        }
        isDeleting={isDeleting}
        onCancel={() => setDeleteTargetId(null)}
        onConfirm={async () => {
          if (deleteTargetId) {
            await deletePerson(deleteTargetId);
            setDeleteTargetId(null);
          }
        }}
      />
      {mergeSource && mergeTarget && (
        <MergeConfirmDialog
          source={mergeSource}
          target={mergeTarget}
          isMerging={isMerging}
          onCancel={handleMergeCancel}
          onConfirm={handleMergeConfirm}
        />
      )}
    </div>
  );
}
