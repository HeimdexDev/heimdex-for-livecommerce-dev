"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { cn } from "@/lib/utils";
import { AvatarThumbnail } from "@/components/people/AvatarThumbnail";
import type { PersonResponse } from "@/lib/types";

function EllipsisVerticalIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 12.75a.75.75 0 110-1.5.75.75 0 010 1.5zM12 18.75a.75.75 0 110-1.5.75.75 0 010 1.5z" />
    </svg>
  );
}

export interface VideoPersonAvatarProps {
  person: PersonResponse;
  isSelected: boolean;
  onSelect: (personClusterId: string) => void;
  onDelete: (personClusterId: string) => void;
  onRename: (personClusterId: string) => void;
  agentAvailable: boolean;
  isDragActive?: boolean;
}

export function VideoPersonAvatar({
  person,
  isSelected,
  onSelect,
  onDelete,
  onRename,
  agentAvailable,
  isDragActive = false,
}: VideoPersonAvatarProps) {
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

  const handleSelect = useCallback(() => {
    onSelect(person.person_cluster_id);
  }, [onSelect, person.person_cluster_id]);

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "group relative flex flex-col items-center gap-1 transition-opacity",
        isDragging && "opacity-30",
        isDragActive && !isDragging && !isOver && "opacity-60",
      )}
      {...attributes}
      {...listeners}
    >
      <button
        type="button"
        onClick={handleSelect}
        className="flex flex-col items-center"
      >
        <AvatarThumbnail
          person={person}
          agentAvailable={agentAvailable}
          className={cn(
            isSelected && "ring-2 ring-indigo-500 ring-offset-2",
            !isSelected && !isOver && "hover:bg-gray-200",
            isOver && "ring-2 ring-indigo-500 scale-105",
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
          >
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setMenuOpen(false); onRename(person.person_cluster_id); }}
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
        <span className="max-w-[96px] truncate text-xs text-gray-600">
          {person.label}
        </span>
      )}
    </div>
  );
}
