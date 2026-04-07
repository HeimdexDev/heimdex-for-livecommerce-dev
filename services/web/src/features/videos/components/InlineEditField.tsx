"use client";

import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";

interface InlineEditFieldProps {
  value: string;
  fieldName: string;
  isEdited?: boolean;
  onSave: (fieldName: string, value: string) => Promise<void>;
  onReset?: (fieldName: string) => Promise<void>;
  multiline?: boolean;
  maxLength?: number;
  placeholder?: string;
}

function PencilIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931z" />
    </svg>
  );
}

export function InlineEditField({
  value,
  fieldName,
  isEdited,
  onSave,
  onReset,
  multiline = true,
  maxLength = 5000,
  placeholder = "",
}: InlineEditFieldProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [isSaving, setIsSaving] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    if (isEditing) {
      const el = multiline ? textareaRef.current : inputRef.current;
      el?.focus();
      el?.select();
    }
  }, [isEditing, multiline]);

  const handleSave = async () => {
    if (draft === value) {
      setIsEditing(false);
      return;
    }
    setIsSaving(true);
    try {
      await onSave(fieldName, draft);
      setIsEditing(false);
    } catch {
      setDraft(value);
    } finally {
      setIsSaving(false);
    }
  };

  const handleCancel = () => {
    setDraft(value);
    setIsEditing(false);
  };

  const handleReset = async () => {
    if (!onReset) return;
    setIsSaving(true);
    try {
      await onReset(fieldName);
      setIsEditing(false);
    } finally {
      setIsSaving(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      handleCancel();
    } else if (e.key === "Enter" && !multiline) {
      e.preventDefault();
      handleSave();
    } else if (e.key === "Enter" && e.metaKey) {
      e.preventDefault();
      handleSave();
    }
  };

  if (isEditing) {
    return (
      <div className="space-y-2">
        {multiline ? (
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value.slice(0, maxLength))}
            onKeyDown={handleKeyDown}
            rows={4}
            maxLength={maxLength}
            className="w-full rounded-lg border border-indigo-300 px-3 py-2 text-sm text-gray-700 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-y"
            placeholder={placeholder}
          />
        ) : (
          <input
            ref={inputRef}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value.slice(0, maxLength))}
            onKeyDown={handleKeyDown}
            maxLength={maxLength}
            className="w-full rounded-lg border border-indigo-300 px-3 py-2 text-sm text-gray-700 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            placeholder={placeholder}
          />
        )}
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
          {multiline && (
            <span className="ml-auto text-[10px] text-gray-400">
              {draft.length}/{maxLength} | Cmd+Enter 저장
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="group relative">
      <p className={cn(
        "text-sm leading-relaxed text-gray-600 whitespace-pre-wrap",
        !value && "italic text-gray-400",
      )}>
        {value || placeholder || "(비어 있음)"}
      </p>
      <div className="absolute -top-1 -right-1 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {isEdited && (
          <span className="rounded-full bg-amber-50 border border-amber-200 px-1.5 py-0.5 text-[9px] font-medium text-amber-700">
            수정됨
          </span>
        )}
        <button
          type="button"
          onClick={() => setIsEditing(true)}
          className="rounded-md bg-white border border-gray-200 p-1 text-gray-400 hover:text-indigo-600 hover:border-indigo-300 shadow-sm transition-colors"
          title="편집"
        >
          <PencilIcon />
        </button>
      </div>
    </div>
  );
}
