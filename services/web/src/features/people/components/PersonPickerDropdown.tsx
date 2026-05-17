"use client";

import { useState, useRef, useEffect } from "react";
import { getFaceThumbnailUrl } from "@/lib/agent";
import { PersonIcon } from "@/components/icons";
import { cn } from "@/lib/utils";
import type { PersonResponse } from "@/lib/types";

interface PersonPickerDropdownProps {
  people: PersonResponse[];
  excludeIds: string[];
  isLinking: boolean;
  onSelect: (person: PersonResponse) => void;
  onClose: () => void;
}

export function PersonPickerDropdown({
  people,
  excludeIds,
  isLinking,
  onSelect,
  onClose,
}: PersonPickerDropdownProps) {
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [onClose]);

  const excludeSet = new Set(excludeIds);
  const filtered = people.filter((p) => {
    if (excludeSet.has(p.person_cluster_id)) return false;
    if (!search) return true;
    return p.label?.toLowerCase().includes(search.toLowerCase());
  });

  return (
    <div
      ref={containerRef}
      className="absolute right-0 top-full z-50 mt-1 w-72 rounded-lg border border-gray-200 bg-white shadow-xl"
    >
      <div className="border-b border-gray-100 p-2">
        <input
          ref={inputRef}
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="인물 검색..."
          className="w-full rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:border-indigo-300 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>
      <div className="max-h-60 overflow-y-auto p-1">
        {filtered.length === 0 ? (
          <p className="px-3 py-4 text-center text-sm text-gray-400">
            {search ? "검색 결과가 없습니다" : "연결 가능한 인물이 없습니다"}
          </p>
        ) : (
          filtered.map((person) => (
            <PersonPickerItem
              key={person.person_cluster_id}
              person={person}
              isLinking={isLinking}
              onSelect={onSelect}
            />
          ))
        )}
      </div>
    </div>
  );
}

function PersonPickerItem({
  person,
  isLinking,
  onSelect,
}: {
  person: PersonResponse;
  isLinking: boolean;
  onSelect: (person: PersonResponse) => void;
}) {
  const [imgError, setImgError] = useState(false);
  const faceUrl = getFaceThumbnailUrl(person.person_cluster_id);

  return (
    <button
      type="button"
      onClick={() => onSelect(person)}
      disabled={isLinking}
      className={cn(
        "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors",
        "hover:bg-gray-50 disabled:opacity-50",
      )}
    >
      {!imgError ? (
        <img
          src={faceUrl}
          alt={person.label ?? "인물"}
          className="h-8 w-8 flex-shrink-0 rounded-full object-cover"
          onError={() => setImgError(true)}
        />
      ) : (
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100">
          <PersonIcon className="h-5 w-5 text-gray-400" />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <span className={cn("block truncate text-sm", person.label ? "text-gray-900" : "text-gray-400")}>
          {person.label || "이름 없음"}
        </span>
        {person.face_count > 0 && (
          <span className="text-xs text-gray-400">{person.face_count}개 장면</span>
        )}
      </div>
    </button>
  );
}
