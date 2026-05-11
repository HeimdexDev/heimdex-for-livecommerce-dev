// ============================================================================
// Local edit state for the auto-shorts subtitle editor (PR 2 of
// auto-shorts-subtitle-editor-2026-05-06.md).
//
// Holds an in-memory copy of the subtitle list + a debounced auto-save
// to ``PATCH /api/shorts/render/{id}/subtitles`` (existing endpoint).
// Surfaces save status + a hasUnsavedEdits flag for the component to
// render banners and disable the "Render with my edits" button while
// a save is in flight.
//
// Korean IME safety lives in the COMPONENT (compositionstart /
// compositionend events) — the hook only sees committed text updates.
//
// Decoupled by design:
//   - No knowledge of the refinement chain (parent vs child) or
//     useRefinedRenderChain — that composes at the page layer.
//   - No fetch logic — uses ``patchRenderJobSubtitles`` from
//     ``@/lib/api/highlight-reel``, which mocks cleanly in vitest.
// ============================================================================

import { useCallback, useEffect, useRef, useState } from "react";

import {
  patchRenderJobSubtitles,
  type RenderJobResponse,
  type SubtitleEdit,
} from "@/lib/api/highlight-reel";

type TokenGetter = () => Promise<string | null>;

export type SaveStatus = "idle" | "saving" | "saved" | "error";

export const DEFAULT_DEBOUNCE_MS = 1500;

export interface UseSubtitleEditorStateOptions {
  /** The render job whose subtitles are being edited. */
  renderId: string;
  /**
   * Cues at hook mount time. Re-keyed when ``renderId`` changes
   * (the hook resets its internal state). Subsequent server-side
   * mutations (e.g. a Whisper refinement landing concurrently) are
   * NOT re-pulled by this hook — that's the page's concern.
   */
  initialCues: SubtitleEdit[];
  /** Auth token getter passed through to the API helper. */
  getToken: TokenGetter;
  /**
   * Debounce window between the last edit and the auto-save fire.
   * Default 1500ms. Tests pass shorter values (~10ms) so they
   * don't sleep half a second per assertion.
   */
  debounceMs?: number;
  /** Optional success callback — fires after a save lands. */
  onSaveSuccess?: (response: RenderJobResponse) => void;
}

export interface UseSubtitleEditorStateResult {
  /** Current cue list (local + optimistic). */
  cues: SubtitleEdit[];
  /**
   * Update one cue by index. Triggers a debounced save. Partial
   * updates merge with the existing cue (text-only edits don't need
   * to re-send timing).
   */
  updateCue: (index: number, partial: Partial<SubtitleEdit>) => void;
  /** Replace the entire cue list. Use when bulk-editing or after a
   * page-level reload (e.g., a refined child landed and the page
   * passes fresh cues down). Does NOT auto-save — caller decides. */
  replaceCues: (cues: SubtitleEdit[]) => void;
  /**
   * Bulk replace + dirty + schedule a debounced save. Use for
   * page-level style updates that overwrite every cue at once
   * (Phase C of edit-clips-right-panel-tabs).
   */
  replaceCuesAndSave: (cues: SubtitleEdit[]) => void;
  saveStatus: SaveStatus;
  saveError: Error | null;
  /** True once any edit has fired since the last successful save. */
  hasUnsavedEdits: boolean;
  /**
   * Flush the pending save immediately (cancels the debounce timer).
   * Returns the promise so the caller can ``await`` before doing
   * something that depends on the latest server state (e.g. a
   * "Render with my edits" call right after a final keystroke).
   */
  flushNow: () => Promise<void>;
}

export function useSubtitleEditorState({
  renderId,
  initialCues,
  getToken,
  debounceMs = DEFAULT_DEBOUNCE_MS,
  onSaveSuccess,
}: UseSubtitleEditorStateOptions): UseSubtitleEditorStateResult {
  const [cues, setCues] = useState<SubtitleEdit[]>(initialCues);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [saveError, setSaveError] = useState<Error | null>(null);
  const [hasUnsavedEdits, setHasUnsavedEdits] = useState(false);

  // Refs that the debounced save closure reads — avoids stale-closure
  // bugs when consecutive edits within the debounce window mutate the
  // cue list before the save fires.
  const pendingCuesRef = useRef<SubtitleEdit[]>(initialCues);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMountedRef = useRef(true);
  // Track which renderId the most recent fetch was started for, so a
  // late-resolving save can be discarded on a renderId pivot.
  const renderIdRef = useRef(renderId);

  // Re-key on renderId change — the hook is single-render-scoped.
  useEffect(() => {
    renderIdRef.current = renderId;
    setCues(initialCues);
    setSaveStatus("idle");
    setSaveError(null);
    setHasUnsavedEdits(false);
    pendingCuesRef.current = initialCues;
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [renderId]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (debounceTimerRef.current !== null) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const performSave = useCallback(async (): Promise<void> => {
    const cuesToSave = pendingCuesRef.current;
    const renderIdAtCallTime = renderIdRef.current;
    setSaveStatus("saving");
    setSaveError(null);
    try {
      const response = await patchRenderJobSubtitles(
        renderIdAtCallTime,
        cuesToSave,
        getToken,
      );
      // If the renderId pivoted while the save was in flight, the
      // response is for a stale target — drop it on the floor.
      if (!isMountedRef.current || renderIdRef.current !== renderIdAtCallTime) {
        return;
      }
      setSaveStatus("saved");
      setHasUnsavedEdits(false);
      onSaveSuccess?.(response);
    } catch (e) {
      if (!isMountedRef.current || renderIdRef.current !== renderIdAtCallTime) {
        return;
      }
      const err = e instanceof Error ? e : new Error(String(e));
      setSaveError(err);
      setSaveStatus("error");
    }
  }, [getToken, onSaveSuccess]);

  const scheduleSave = useCallback(() => {
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
    }
    debounceTimerRef.current = setTimeout(() => {
      debounceTimerRef.current = null;
      void performSave();
    }, debounceMs);
  }, [performSave, debounceMs]);

  const updateCue = useCallback(
    (index: number, partial: Partial<SubtitleEdit>) => {
      setCues((prev) => {
        if (index < 0 || index >= prev.length) {
          return prev;
        }
        const next = prev.map((c, i) =>
          i === index ? { ...c, ...partial } : c,
        );
        pendingCuesRef.current = next;
        return next;
      });
      setHasUnsavedEdits(true);
      scheduleSave();
    },
    [scheduleSave],
  );

  const replaceCues = useCallback((next: SubtitleEdit[]) => {
    setCues(next);
    pendingCuesRef.current = next;
    // Caller-driven reset; not an edit, so don't mark dirty or save.
  }, []);

  const replaceCuesAndSave = useCallback(
    (next: SubtitleEdit[]) => {
      setCues(next);
      pendingCuesRef.current = next;
      setHasUnsavedEdits(true);
      scheduleSave();
    },
    [scheduleSave],
  );

  const flushNow = useCallback(async (): Promise<void> => {
    if (debounceTimerRef.current !== null) {
      clearTimeout(debounceTimerRef.current);
      debounceTimerRef.current = null;
    }
    if (!hasUnsavedEdits) {
      // Nothing to save; honour the contract by resolving immediately
      // so the caller doesn't have to special-case.
      return;
    }
    await performSave();
  }, [hasUnsavedEdits, performSave]);

  return {
    cues,
    updateCue,
    replaceCues,
    replaceCuesAndSave,
    saveStatus,
    saveError,
    hasUnsavedEdits,
    flushNow,
  };
}
