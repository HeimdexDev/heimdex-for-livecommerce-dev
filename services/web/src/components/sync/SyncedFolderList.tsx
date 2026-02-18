"use client";

import { useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { AgentSource } from "@/lib/agent";

interface SyncedFolderListProps {
  sources: AgentSource[];
  onAddFolder: () => void;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
}

function FolderRow({
  source,
  onDelete,
  onRename,
}: {
  source: AgentSource;
  onDelete: (id: string) => void;
  onRename: (id: string, name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(source.display_name);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleSave = useCallback(() => {
    const trimmed = draft.trim();
    if (trimmed && trimmed !== source.display_name) {
      onRename(source.id, trimmed);
    }
    setEditing(false);
  }, [draft, source.id, source.display_name, onRename]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleSave();
      if (e.key === "Escape") {
        setDraft(source.display_name);
        setEditing(false);
      }
    },
    [handleSave, source.display_name],
  );

  return (
    <div className="flex items-center gap-4 rounded-lg border border-gray-100 bg-white px-5 py-4">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-500">
        <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
          <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
        </svg>
      </div>

      <div className="min-w-0 flex-1">
        {editing ? (
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={handleSave}
            onKeyDown={handleKeyDown}
            autoFocus
            className="w-full rounded border border-indigo-300 px-2 py-1 text-sm font-medium text-gray-900 outline-none focus:ring-2 focus:ring-indigo-400"
          />
        ) : (
          <p className="truncate text-sm font-medium text-gray-900">
            {source.display_name}
          </p>
        )}
        <p className="truncate text-xs text-gray-400">{source.path}</p>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
          {source.files_count}
          <span className="ml-0.5 text-gray-400">파일</span>
        </span>

        <span
          className={cn(
            "h-2 w-2 rounded-full",
            source.present ? "bg-emerald-400" : "bg-gray-300",
          )}
        />

        {!editing && (
          <button
            type="button"
            onClick={() => { setDraft(source.display_name); setEditing(true); }}
            className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            title="이름 변경"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
            </svg>
          </button>
        )}

        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => { onDelete(source.id); setConfirmDelete(false); }}
              className="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
            >
              삭제
            </button>
            <button
              type="button"
              onClick={() => setConfirmDelete(false)}
              className="rounded px-2 py-1 text-xs font-medium text-gray-500 hover:bg-gray-100"
            >
              취소
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="rounded p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-500"
            title="삭제"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}

export function SyncedFolderList({ sources, onAddFolder, onDelete, onRename }: SyncedFolderListProps) {
  return (
    <div className="mt-8">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-900">
          동기화된 폴더
          {sources.length > 0 && (
            <span className="ml-2 text-sm font-normal text-gray-400">
              {sources.length}개
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={onAddFolder}
          className="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-600 transition-colors"
        >
          + 폴더 추가
        </button>
      </div>

      {sources.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 py-12 text-center">
          <p className="text-sm text-gray-400">
            동기화된 폴더가 없습니다. 폴더를 추가해 주세요.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {sources.map((s) => (
            <FolderRow key={s.id} source={s} onDelete={onDelete} onRename={onRename} />
          ))}
        </div>
      )}
    </div>
  );
}
