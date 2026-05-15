"use client";

import { useState, useRef } from "react";
import { cn } from "@/lib/utils";

const MAX_TAGS = 7;
const MIN_TAG_LENGTH = 2;
const MAX_TAG_LENGTH = 15;

interface TagEditorProps {
  tags: string[];
  isEdited?: boolean;
  onSave: (tags: string[]) => Promise<void>;
  onReset?: () => Promise<void>;
}

export function TagEditor({ tags, isEdited, onSave, onReset }: TagEditorProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>(tags);
  const [input, setInput] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleAdd = () => {
    const trimmed = input.trim();
    setError(null);

    if (!trimmed) return;
    if (trimmed.length < MIN_TAG_LENGTH || trimmed.length > MAX_TAG_LENGTH) {
      setError(`태그는 ${MIN_TAG_LENGTH}-${MAX_TAG_LENGTH}자여야 합니다`);
      return;
    }
    if (draft.length >= MAX_TAGS) {
      setError(`최대 ${MAX_TAGS}개까지 가능합니다`);
      return;
    }
    if (draft.includes(trimmed)) {
      setError("이미 존재하는 태그입니다");
      return;
    }

    setDraft([...draft, trimmed]);
    setInput("");
  };

  const handleRemove = (tag: string) => {
    setDraft(draft.filter((t) => t !== tag));
    setError(null);
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(draft);
      setIsEditing(false);
    } catch {
      setDraft(tags);
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    setDraft(tags);
    setInput("");
    setError(null);
    setIsEditing(false);
  };

  const handleReset = async () => {
    if (!onReset) return;
    setIsSaving(true);
    try {
      await onReset();
      setIsEditing(false);
    } finally {
      setIsSaving(false);
    }
  };

  if (!isEditing) {
    return (
      <div className="group flex items-center gap-1 flex-wrap">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"
          >
            {tag}
          </span>
        ))}
        {tags.length === 0 && (
          <span className="text-xs text-gray-400 italic">(태그 없음)</span>
        )}
        {isEdited && (
          <span className="rounded-full bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-[9px] font-medium text-amber-700">
            수정됨
          </span>
        )}
        <button
          type="button"
          onClick={() => { setIsEditing(true); setDraft(tags); }}
          className="opacity-0 group-hover:opacity-100 rounded-md bg-white border border-gray-200 p-0.5 text-gray-400 hover:text-indigo-600 hover:border-indigo-300 shadow-sm transition-all"
          title="태그 편집"
        >
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {draft.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700"
          >
            {tag}
            <button
              type="button"
              onClick={() => handleRemove(tag)}
              className="ml-0.5 text-emerald-400 hover:text-red-500"
            >
              x
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => { setInput(e.target.value); setError(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAdd(); } }}
          placeholder="태그 입력 후 Enter"
          maxLength={MAX_TAG_LENGTH}
          className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={draft.length >= MAX_TAGS}
          className="rounded-md bg-emerald-50 border border-emerald-200 px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
        >
          추가
        </button>
      </div>
      {error && <p className="text-[10px] text-red-500">{error}</p>}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={isSaving}
          className="rounded-md bg-indigo-500 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-600 disabled:opacity-50"
        >
          {isSaving ? "저장 중..." : "저장"}
        </button>
        <button
          type="button"
          onClick={handleCancel}
          disabled={isSaving}
          className="rounded-md border border-gray-200 px-3 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        >
          취소
        </button>
        {isEdited && onReset && (
          <button
            type="button"
            onClick={handleReset}
            disabled={isSaving}
            className="ml-auto rounded-md border border-amber-200 px-3 py-1 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50"
          >
            원래 값 복원
          </button>
        )}
      </div>
    </div>
  );
}
