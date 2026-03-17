"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import Link from "next/link";
import { useAgent } from "@/features/search/hooks/useAgent";
import { useVideoPeople } from "../hooks/useVideoPeople";
import { VideoPersonAvatar } from "./VideoPersonAvatar";
import { PersonSceneGrid } from "./PersonSceneGrid";
import { DeletePersonDialog } from "@/features/people/components/DeletePersonDialog";
import { getFaceThumbnailUrl, getCloudThumbnailUrl } from "@/lib/agent";
import { PersonIcon } from "@/components/icons";
import { cn } from "@/lib/utils";
import type { PersonResponse, VideoScene } from "@/lib/types";
import type { ThumbnailAspectRatio } from "@/lib/thumbnailUtils";

function PencilIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487z" />
    </svg>
  );
}

function ArrowRightIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
    </svg>
  );
}

interface VideoPeoplePanelProps {
  videoId: string;
  scenes?: VideoScene[];
  onSeekToScene?: (startMs: number) => void;
  agentAvailable?: boolean;
  aspectRatio?: ThumbnailAspectRatio;
}

function InlinePersonDetail({
  person,
  onRename,
  isRenaming,
  onDelete,
}: {
  person: PersonResponse;
  onRename: (personClusterId: string, label: string | null) => Promise<void>;
  isRenaming: boolean;
  onDelete: (personClusterId: string) => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(person.label ?? "");
  const [imgError, setImgError] = useState(false);
  const [useFallback, setUseFallback] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const faceUrl = getFaceThumbnailUrl(person.person_cluster_id);
  const sceneUrl =
    person.representative_video_id && person.representative_scene_id
      ? getCloudThumbnailUrl(person.representative_video_id, person.representative_scene_id)
      : null;
  const thumbnailUrl = !useFallback ? faceUrl : sceneUrl;

  // Reset edit state when person changes
  useEffect(() => {
    setIsEditing(false);
    setEditValue(person.label ?? "");
    setImgError(false);
    setUseFallback(false);
  }, [person.person_cluster_id, person.label]);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

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
        {thumbnailUrl && !imgError ? (
          <img
            src={thumbnailUrl}
            alt={person.label ?? "인물"}
            className="h-8 w-8 flex-shrink-0 rounded-full object-cover"
            onError={() => {
              if (!useFallback && sceneUrl) {
                setUseFallback(true);
              } else {
                setImgError(true);
              }
            }}
          />
        ) : (
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
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

      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {person.face_count}개 장면에서 등장
        </span>
        <button
          type="button"
          onClick={() => onDelete(person.person_cluster_id)}
          className="rounded-md border border-red-200 px-2.5 py-1 text-xs text-red-600 transition-colors hover:bg-red-50"
        >
          삭제
        </button>
      </div>
    </div>
  );
}

export function VideoPeoplePanel({
  videoId,
  scenes,
  onSeekToScene,
  agentAvailable: agentAvailableProp,
  aspectRatio = "16:9",
}: VideoPeoplePanelProps) {
  const { isAvailable: agentAvailableFromHook } = useAgent();
  const agentAvailable = agentAvailableProp ?? agentAvailableFromHook;
  const {
    people,
    isLoading,
    error,
    renamePerson,
    isRenaming,
    deletePerson,
    isDeleting,
  } = useVideoPeople(videoId);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);

  // Clear selection when people list changes (e.g. after delete)
  useEffect(() => {
    if (selectedId && !people.find((p) => p.person_cluster_id === selectedId)) {
      setSelectedId(null);
    }
  }, [people, selectedId]);

  const selectedPerson = people.find((p) => p.person_cluster_id === selectedId) ?? null;

  const personScenes = useMemo(() => {
    if (!selectedId || !scenes?.length) return [];
    return scenes.filter((s) => s.people_cluster_ids.includes(selectedId));
  }, [scenes, selectedId]);

  const handleSelect = useCallback((personClusterId: string) => {
    setSelectedId((prev) => (prev === personClusterId ? null : personClusterId));
  }, []);

  const handleRenameFromAvatar = useCallback((personClusterId: string) => {
    setSelectedId(personClusterId);
  }, []);

  const handleDeleteConfirm = useCallback(async () => {
    if (!deleteTargetId) return;
    await deletePerson(deleteTargetId);
    setDeleteTargetId(null);
  }, [deleteTargetId, deletePerson]);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900">인물 관리</h2>
        <Link
          href="/settings/people"
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 transition-colors hover:text-gray-700"
        >
          전체 인물 관리
          <ArrowRightIcon />
        </Link>
      </div>

      {/* Error */}
      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Loading */}
      {isLoading ? (
        <div className="flex min-h-[200px] items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      ) : people.length === 0 ? (
        /* Empty State */
        <div className="mt-8 flex flex-col items-center py-12">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gray-100">
            <PersonIcon className="h-8 w-8 text-gray-400" />
          </div>
          <h3 className="mt-4 text-sm font-medium text-gray-900">
            이 영상에서 인식된 인물이 없습니다.
          </h3>
          <p className="mt-1 text-xs text-gray-500">
            얼굴 인식은 영상 업로드 후 자동으로 처리됩니다.
          </p>
        </div>
      ) : (
        <>
          {/* Avatar Grid */}
          <div className="mt-6 grid grid-cols-4 gap-5">
            {people.map((person) => (
              <VideoPersonAvatar
                key={person.person_cluster_id}
                person={person}
                isSelected={selectedId === person.person_cluster_id}
                onSelect={handleSelect}
                onDelete={setDeleteTargetId}
                onRename={handleRenameFromAvatar}
                agentAvailable={agentAvailable}
              />
            ))}
          </div>

          {/* Inline Detail */}
          {selectedPerson && (
            <div className="mt-6 space-y-4">
              <InlinePersonDetail
                person={selectedPerson}
                onRename={renamePerson}
                isRenaming={isRenaming}
                onDelete={setDeleteTargetId}
              />
              {scenes && (
                <PersonSceneGrid
                  scenes={personScenes}
                  videoId={videoId}
                  agentAvailable={agentAvailable}
                  aspectRatio={aspectRatio}
                  onSceneClick={onSeekToScene}
                />
              )}
            </div>
          )}
        </>
      )}

      {/* Delete Dialog */}
      <DeletePersonDialog
        isOpen={deleteTargetId !== null}
        personLabel={
          people.find((p) => p.person_cluster_id === deleteTargetId)?.label ?? null
        }
        isDeleting={isDeleting}
        onCancel={() => setDeleteTargetId(null)}
        onConfirm={handleDeleteConfirm}
      />
    </div>
  );
}
