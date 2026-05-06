// ============================================================================
// SubtitleEditor — inline auto-shorts subtitle editing surface (PR 2 of
// auto-shorts-subtitle-editor-2026-05-06.md).
//
// Pure presentation + state-glue. The actual debounced auto-save lives
// in `useSubtitleEditorState`. Komentary on layout decisions:
//
//   - Per-cue row: read-only timestamp + `<textarea>` for text. PR 4
//     promotes the timestamp to draggable handles; for now it's a
//     fixed strip.
//   - Korean IME safety: composition events suppress on-blur saves so
//     a save doesn't fire mid-Hangul-composition (mid-사 → "사" save
//     would be wrong).
//   - "Render with my edits" button: explicit cost action. Disabled
//     while a save or render is in flight, and while there are
//     unsaved edits (the page-level handler should `flushNow()` first).
//   - Banner copy is Korean (operator-facing). Source of truth is the
//     plan doc's open-questions section.
// ============================================================================

import { useEffect, useRef, useState, type ChangeEvent } from "react";

import {
  useSubtitleEditorState,
  type SaveStatus,
} from "@/features/shorts-auto-product-wizard/hooks/useSubtitleEditorState";
import {
  fetchRenderSubtitles,
  type RenderJobResponse,
  type SubtitleDownloadFormat,
  type SubtitleEdit,
} from "@/lib/api/highlight-reel";

type TokenGetter = () => Promise<string | null>;

export interface SubtitleEditorProps {
  /** The render currently in focus. The hook re-keys on this. */
  renderId: string;
  /** Subtitles loaded from the parent's input_spec. */
  initialCues: SubtitleEdit[];
  /** Auth token getter; passed through to the API helper. */
  getToken: TokenGetter;
  /**
   * The render's ``refinement_source``. Used to surface a banner
   * when the user has dirtied the cues but the parent hasn't yet
   * flipped to ``manual_edit`` (i.e., the auto-save hasn't landed).
   */
  refinementSource: RenderJobResponse["refinement_source"];
  /**
   * Called when the user clicks "Render with my edits". The page
   * is responsible for: (a) ``flushNow``-ing the hook to commit any
   * pending edits, then (b) calling ``rerenderFromEdits``, then (c)
   * pivoting the parent's polling target to the returned child id.
   * The component just signals intent.
   */
  onRerenderRequested: () => Promise<void>;
  /**
   * True while a re-render is in flight. The component disables the
   * button and shows progress copy. Source of truth: the page's
   * ``useRefinedRenderChain`` hook (``stage === 'polling_child'``).
   */
  isRendering: boolean;
  /**
   * Optional. Fires whenever the editor's internal cue list changes
   * — including the initial replay on mount + after each
   * ``updateCue``. The page uses this to mirror the live cues into
   * its in-player DOM overlay so operators can preview edits before
   * paying for a re-render.
   */
  onCuesChange?: (cues: SubtitleEdit[]) => void;
}

/** Display ``mm:ss.cs`` for a millisecond timestamp. */
function formatMs(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSec / 60);
  const seconds = totalSec % 60;
  const centi = Math.floor((ms % 1000) / 10);
  return `${minutes.toString().padStart(2, "0")}:${seconds
    .toString()
    .padStart(2, "0")}.${centi.toString().padStart(2, "0")}`;
}

function saveStatusLabel(status: SaveStatus): string {
  switch (status) {
    case "idle":
      return "";
    case "saving":
      return "저장 중...";
    case "saved":
      return "저장됨";
    case "error":
      return "저장 실패 — 다시 시도해주세요";
  }
}

export function SubtitleEditor({
  renderId,
  initialCues,
  getToken,
  refinementSource,
  onRerenderRequested,
  isRendering,
  onCuesChange,
}: SubtitleEditorProps) {
  const {
    cues,
    updateCue,
    saveStatus,
    saveError,
    hasUnsavedEdits,
    flushNow,
  } = useSubtitleEditorState({
    renderId,
    initialCues,
    getToken,
  });

  // Bubble cue changes up to the page so the in-player DOM overlay
  // can preview unsaved/post-save edits without waiting for a
  // re-render. ``cues`` is a stable reference per render via React
  // memo from inside the hook, so this fires once per actual change.
  const onCuesChangeRef = useRef(onCuesChange);
  useEffect(() => {
    onCuesChangeRef.current = onCuesChange;
  }, [onCuesChange]);
  useEffect(() => {
    onCuesChangeRef.current?.(cues);
  }, [cues]);

  const [downloadStatus, setDownloadStatus] = useState<
    "idle" | "downloading" | "error"
  >("idle");
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // Show the "edits not yet rendered" banner when:
  //   - the user has typed unsaved edits (hasUnsavedEdits=true), OR
  //   - the parent's refinement_source is already 'manual_edit' (so
  //     edits HAVE been saved but no re-render has happened yet — the
  //     downloadable MP4 doesn't reflect them).
  const showRerenderBanner =
    hasUnsavedEdits || refinementSource === "manual_edit";

  // The button is enabled only when there's something to render and
  // we're not already in flight. Saving=true also disables it so the
  // user doesn't fire rerender against pre-save state.
  const renderDisabled =
    isRendering || saveStatus === "saving" || hasUnsavedEdits || cues.length === 0;

  async function handleRerenderClick() {
    if (renderDisabled) return;
    // Defensive flush — even though the button is disabled while
    // hasUnsavedEdits, a stale save error could leave dirty state.
    if (hasUnsavedEdits) {
      await flushNow();
    }
    await onRerenderRequested();
  }

  async function handleDownloadClick(format: SubtitleDownloadFormat) {
    if (downloadStatus === "downloading") return;
    // Flush pending edits first — otherwise the server would serialize
    // the stale pre-debounce subtitles. The PATCH side-effect (sets
    // refinement_source='manual_edit') is harmless if redundant.
    if (hasUnsavedEdits) {
      try {
        await flushNow();
      } catch {
        // The save itself surfaces an error via saveStatus; we still
        // attempt the download below using whatever the server has.
      }
    }
    setDownloadStatus("downloading");
    setDownloadError(null);
    try {
      const { body, filename } = await fetchRenderSubtitles(
        renderId, format, getToken,
      );
      // Anchor click in a same-tab navigation is the only cross-browser
      // way to surface the OS save-as dialog from a fetch result.
      const blob = new Blob([body], {
        type: format === "srt" ? "application/x-subrip" : "text/vtt",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setDownloadStatus("idle");
    } catch (e) {
      setDownloadStatus("error");
      setDownloadError(e instanceof Error ? e.message : "다운로드 실패");
    }
  }

  return (
    <section
      data-testid="subtitle-editor"
      className="flex max-h-[58vh] flex-col gap-3 rounded-md border border-neutral-200 p-4"
    >
      <header className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-neutral-900">자막 편집</h3>
        <span
          data-testid="subtitle-editor-save-status"
          aria-live="polite"
          className={
            saveStatus === "error"
              ? "text-sm text-red-600"
              : "text-sm text-neutral-500"
          }
        >
          {saveStatusLabel(saveStatus)}
        </span>
      </header>

      {showRerenderBanner ? (
        <div
          data-testid="subtitle-editor-banner"
          role="status"
          className="rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-900"
        >
          자막 편집이 아직 영상에 반영되지 않았습니다.
        </div>
      ) : null}

      {cues.length === 0 ? (
        <div className="rounded border border-dashed border-neutral-300 p-4 text-sm text-neutral-500">
          음성 자막을 생성하지 못했습니다.
        </div>
      ) : (
        <div className="grid gap-2 overflow-y-auto pr-1">
          {cues.map((cue, index) => (
            <SubtitleEditorRow
              key={`${renderId}-${index}`}
              index={index}
              cue={cue}
              onTextChange={(text) => updateCue(index, { text })}
            />
          ))}
        </div>
      )}

      {saveError ? (
        <p
          data-testid="subtitle-editor-error"
          className="text-xs text-red-600"
        >
          {saveError.message}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-neutral-100 pt-3">
        {downloadError ? (
          <p
            data-testid="subtitle-editor-download-error"
            className="basis-full text-right text-xs text-red-600"
          >
            {downloadError}
          </p>
        ) : null}
        <button
          type="button"
          data-testid="subtitle-editor-download-srt-button"
          onClick={() => handleDownloadClick("srt")}
          disabled={cues.length === 0 || downloadStatus === "downloading"}
          className={
            cues.length === 0 || downloadStatus === "downloading"
              ? "rounded border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-400"
              : "rounded border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-50"
          }
        >
          {downloadStatus === "downloading" ? "다운로드 중..." : "자막 다운로드 (.srt)"}
        </button>
        <button
          type="button"
          data-testid="subtitle-editor-rerender-button"
          onClick={handleRerenderClick}
          disabled={renderDisabled}
          className={
            renderDisabled
              ? "rounded bg-neutral-200 px-4 py-2 text-sm text-neutral-500"
              : "rounded bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700"
          }
        >
          {isRendering ? "렌더링 중..." : "내 편집으로 다시 렌더링 (~30초)"}
        </button>
      </div>
    </section>
  );
}

interface SubtitleEditorRowProps {
  index: number;
  cue: SubtitleEdit;
  onTextChange: (text: string) => void;
}

function SubtitleEditorRow({ index, cue, onTextChange }: SubtitleEditorRowProps) {
  const [localText, setLocalText] = useState<string>(cue.text);
  const [isComposing, setIsComposing] = useState<boolean>(false);

  // If the parent re-keys (e.g. on renderId pivot), reset local text.
  // We don't use useEffect here because the row's `key` changes, which
  // remounts. State resets to `cue.text` at mount time naturally.

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    const next = e.target.value;
    setLocalText(next);
    if (!isComposing) {
      onTextChange(next);
    }
  }

  function handleCompositionStart() {
    setIsComposing(true);
  }

  function handleCompositionEnd(e: { currentTarget: HTMLTextAreaElement }) {
    setIsComposing(false);
    onTextChange(e.currentTarget.value);
  }

  return (
    <label
      data-testid={`subtitle-editor-row-${index}`}
      className="flex gap-3 rounded border border-neutral-100 bg-white p-2 hover:border-neutral-300"
    >
      <span className="shrink-0 text-xs text-neutral-500">
        {formatMs(cue.start_ms)} – {formatMs(cue.end_ms)}
      </span>
      <textarea
        data-testid={`subtitle-editor-textarea-${index}`}
        value={localText}
        onChange={handleChange}
        onCompositionStart={handleCompositionStart}
        onCompositionEnd={handleCompositionEnd}
        rows={2}
        className="grow resize-none rounded border border-neutral-200 px-2 py-1 text-sm focus:border-neutral-500 focus:outline-none"
      />
    </label>
  );
}
