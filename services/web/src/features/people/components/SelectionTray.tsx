"use client";

import { AvatarThumbnail } from "@/components/people/AvatarThumbnail";
import type { PersonResponse } from "@/lib/types";

export const MAX_TRAY_VISIBLE = 8;

export function SelectionTray({
  selectedPeople,
  agentAvailable,
  onRemove,
  onSelectAll,
  onMerge,
  onDelete,
  onClear,
}: {
  selectedPeople: PersonResponse[];
  agentAvailable: boolean;
  onRemove: (personClusterId: string) => void;
  onSelectAll: () => void;
  onMerge: () => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  const count = selectedPeople.length;
  const visible = selectedPeople.slice(0, MAX_TRAY_VISIBLE);
  const overflowCount = count - visible.length;

  return (
    <div
      data-testid="selection-tray"
      className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-gray-200 bg-white px-4 py-2.5 shadow-xl"
    >
      <div className="flex items-center gap-1.5">
        {visible.map((person) => (
          <div
            key={person.person_cluster_id}
            className="group/tray relative"
          >
            <AvatarThumbnail
              person={person}
              agentAvailable={agentAvailable}
              className="h-10 w-10 rounded-lg ring-1 ring-indigo-200"
            />
            <button
              type="button"
              aria-label={`${person.label ?? "인물"} 선택 해제`}
              onClick={() => onRemove(person.person_cluster_id)}
              className="absolute -right-1 -top-1 hidden h-4 w-4 items-center justify-center rounded-full bg-gray-600 text-[10px] leading-none text-white hover:bg-gray-800 group-hover/tray:flex"
            >
              ✕
            </button>
          </div>
        ))}
        {overflowCount > 0 && (
          <span
            data-testid="overflow-badge"
            className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-100 text-xs font-medium text-gray-500"
          >
            +{overflowCount}
          </span>
        )}
      </div>

      <div className="h-8 w-px bg-gray-200" />

      <span className="whitespace-nowrap text-sm font-medium text-gray-700">
        {count}명 선택됨
      </span>

      <button
        type="button"
        onClick={onSelectAll}
        className="rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-800"
      >
        전체 선택
      </button>

      {count >= 2 && (
        <>
          <button
            type="button"
            onClick={onMerge}
            className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            병합
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700"
          >
            삭제
          </button>
        </>
      )}

      <button
        type="button"
        onClick={onClear}
        className="rounded-md px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-700"
      >
        취소
      </button>
    </div>
  );
}
