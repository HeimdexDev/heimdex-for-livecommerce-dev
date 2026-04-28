"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";
import type { ScoringModeRequest } from "@/lib/types";

import { ModePicker } from "./ModePicker";
import { PersonSelect } from "./PersonSelect";
import { MagicWandIcon } from "./icons";

interface ModeReselectModalProps {
  open: boolean;
  videoId: string;
  /** Initial mode the modal opens with — staged locally so the user
   * can dismiss without affecting the page state. */
  initialMode: ScoringModeRequest;
  initialPersonClusterId: string | null;
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (mode: ScoringModeRequest, personClusterId: string | null) => void;
}

/**
 * Phase 1 mode reselect — Option 5 from the plan.
 *
 * Wraps the existing ``ModePicker`` and ``PersonSelect`` so the user can
 * change their mode + (when human) their person without leaving the
 * page. State is staged locally inside the modal — only commits to
 * the page on submit so cancel is non-destructive.
 *
 * Person mode is BLOCKING per locked decision: the submit button is
 * disabled until a person is picked, and the inline picker stays
 * visible until that's resolved.
 *
 * PR 5 will replace this modal with an in-page tab strip
 * (Option 2 from the plan).
 */
export function ModeReselectModal({
  open,
  videoId,
  initialMode,
  initialPersonClusterId,
  isLoading,
  onClose,
  onSubmit,
}: ModeReselectModalProps) {
  const [mode, setMode] = useState<ScoringModeRequest>(initialMode);
  const [personClusterId, setPersonClusterId] = useState<string | null>(
    initialPersonClusterId,
  );

  // Reset staged state whenever the modal opens with new initials —
  // user expects to see the current selections, not stale ones.
  useEffect(() => {
    if (open) {
      setMode(initialMode);
      setPersonClusterId(initialPersonClusterId);
    }
  }, [open, initialMode, initialPersonClusterId]);

  // Wire Escape-to-close so keyboard users can dismiss without
  // hunting for the X. Only when open.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  const canSubmit =
    !isLoading && (mode !== "human" || Boolean(personClusterId));

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="mode-reselect-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-100 text-indigo-600">
              <MagicWandIcon />
            </span>
            <div>
              <h2 id="mode-reselect-title" className="text-base font-semibold text-gray-900">
                모드 다시 선택
              </h2>
              <p className="mt-0.5 text-xs text-gray-500">
                AI가 영상을 다시 분석해 새로운 클립을 만들어 드립니다.
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="닫기"
            className="rounded-md p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            onClick={onClose}
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <h3 className="mb-2 text-sm font-medium text-gray-700">1. 모드 선택</h3>
            <ModePicker
              value={mode}
              onChange={(next) => {
                setMode(next);
                if (next !== "human") setPersonClusterId(null);
              }}
              disabled={isLoading}
            />
          </div>

          {mode === "human" && (
            <div>
              <h3 className="mb-2 text-sm font-medium text-gray-700">2. 인물 선택</h3>
              <PersonSelect
                videoId={videoId}
                value={personClusterId}
                onChange={setPersonClusterId}
                disabled={isLoading}
              />
              <p className="mt-1 text-xs text-gray-400">
                선택한 인물이 등장하는 장면만 쇼츠에 포함됩니다.
              </p>
            </div>
          )}
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            취소
          </button>
          <button
            type="button"
            onClick={() => onSubmit(mode, mode === "human" ? personClusterId : null)}
            disabled={!canSubmit}
            className={cn(
              "inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
              canSubmit
                ? "bg-indigo-500 hover:bg-indigo-600"
                : "cursor-not-allowed bg-gray-300",
            )}
          >
            {isLoading ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              <MagicWandIcon className="h-4 w-4" />
            )}
            {isLoading ? "분석 중..." : "다시 생성"}
          </button>
        </div>
      </div>
    </div>
  );
}
