"use client";

import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
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
import { getPersonVideos, getVideoExclusions, saveVideoExclusions } from "@/lib/api/people";
import { getCloudThumbnailUrl, getFaceThumbnailUrl } from "@/lib/agent";
import type { PersonResponse, PersonVideoItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ScenePreviewTooltip } from "@/components/ScenePreviewTooltip";
import { DeletePersonDialog } from "./DeletePersonDialog";
import { MergeConfirmDialog } from "./MergeConfirmDialog";

function PersonIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"
      />
    </svg>
  );
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
  agentAvailable,
  isDragActive,
}: {
  person: PersonResponse;
  isSelected: boolean;
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
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

  return (
    <ScenePreviewTooltip
      videoId={person.representative_video_id}
      sceneId={person.representative_scene_id}
      label={person.label}
      badge={`${person.face_count}개 장면`}
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
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(person.person_cluster_id);
          }}
          className="absolute -right-1 -top-1 hidden rounded-full bg-white p-1 shadow-md transition-colors hover:bg-red-50 hover:text-red-500 group-hover:block"
          title="삭제"
        >
          <TrashIcon />
        </button>
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
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(person.label ?? "");
  const [videoFiles, setVideoFiles] = useState<PersonVideoItem[]>([]);
  const [loadingVideos, setLoadingVideos] = useState(true);
  const [headerImgError, setHeaderImgError] = useState(false);
  const [headerUseFallback, setHeaderUseFallback] = useState(false);
  const [checkedVideos, setCheckedVideos] = useState<Set<string>>(new Set());
  const [excludedVideoIds, setExcludedVideoIds] = useState<Set<string>>(new Set());
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
    let cancelled = false;
    setLoadingVideos(true);

    Promise.all([
      getPersonVideos(person.person_cluster_id, getToken),
      getVideoExclusions(person.person_cluster_id, getToken),
    ])
      .then(([videosRes, exclusionsRes]) => {
        if (cancelled) return;
        setVideoFiles(videosRes.videos);
        const excl = new Set(exclusionsRes.excluded_video_ids);
        setExcludedVideoIds(excl);
        setCheckedVideos(
          new Set(videosRes.videos.map((v) => v.video_id).filter((id) => !excl.has(id))),
        );
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
      setCheckedVideos((prev) => {
        const next = new Set(prev);
        if (next.has(videoId)) next.delete(videoId);
        else next.add(videoId);
        return next;
      });

      setExcludedVideoIds((prev) => {
        const next = new Set(prev);
        if (next.has(videoId)) next.delete(videoId);
        else next.add(videoId);

        // Debounced save
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
          videoFiles.slice(0, 7).map((video) => {
            const isChecked = checkedVideos.has(video.video_id);
            return (
              <button
                key={video.video_id}
                type="button"
                onClick={() => toggleVideo(video.video_id)}
                className="flex w-full items-center justify-between rounded px-1 py-1 hover:bg-gray-50"
              >
                <span className="truncate text-sm text-gray-700">
                  {video.video_title || video.video_id}
                </span>
                <div
                  className={cn(
                    "flex h-5 w-5 flex-shrink-0 items-center justify-center rounded transition-colors",
                    isChecked
                      ? "bg-indigo-500"
                      : "border border-gray-300 bg-white",
                  )}
                >
                  {isChecked && <CheckIcon />}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
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

  const filteredPeople = useMemo(() => {
    if (!searchQuery.trim()) return people;
    const q = searchQuery.trim().toLowerCase();
    return people.filter(
      (p) =>
        p.label?.toLowerCase().includes(q) ||
        p.person_cluster_id.toLowerCase().includes(q),
    );
  }, [people, searchQuery]);

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
                    {filteredPeople.map((person) => (
                      <PersonAvatar
                        key={person.person_cluster_id}
                        person={person}
                        isSelected={selectedIds.has(person.person_cluster_id)}
                        onToggle={toggleSelection}
                        onDelete={setDeleteTargetId}
                        agentAvailable={agentAvailable}
                        isDragActive={activeDragPerson !== null}
                      />
                    ))}
                  </div>
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
