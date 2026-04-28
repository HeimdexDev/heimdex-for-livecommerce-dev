"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { cn } from "@/lib/utils";
import type { AutoClipResponse, VideoScene } from "@/lib/types";

import { ScriptPanel } from "./ScriptPanel";

interface InspectorPanelProps {
  clip: AutoClipResponse | null;
  scenes: VideoScene[];
  /** Editor deep link for the active clip — passed in so the page owns URL building. */
  editorHref: string | null;
  /** Disabled when no clip is selected or while a render is mid-flight. */
  onDownload?: () => void;
  isDownloading?: boolean;
  /**
   * Server-side title for the selected clip's render job (when one
   * exists). When ``null``, no render-job has been created yet — the
   * title input falls back to a derived placeholder and is disabled.
   */
  renderJobTitle?: string | null;
  /**
   * Save callback fired on blur when the title changed. ``undefined``
   * when no render-job exists (input rendered as disabled with a
   * tooltip explaining the user has to render first).
   */
  onTitleSave?: (title: string | null) => Promise<void> | void;
}

/**
 * Right-rail inspector for the active clip.
 *
 * Sections (top to bottom):
 *   1. Quick actions — 편집하기 (deep link to editor) + 다운로드 (mirrors
 *      the card's button so the user has a primary action without
 *      hunting back to the list).
 *   2. 제목 — editable when a render-job exists for the selected clip
 *      (Phase 3 added the PATCH endpoint). Disabled before that with a
 *      tooltip directing the user to render first.
 *   3. 원본 영상 타임라인 — span readout in M분 S초 format matching the
 *      reference design.
 *   4. 스크립트 — speaker-diarized script panel.
 *
 * No social-upload section per locked decision (deferred entirely; not
 * even a stub).
 */
export function InspectorPanel({
  clip,
  scenes,
  editorHref,
  onDownload,
  isDownloading,
  renderJobTitle,
  onTitleSave,
}: InspectorPanelProps) {
  if (!clip) {
    return (
      <div className="p-6 text-sm text-gray-400">
        클립을 선택하면 자세한 정보가 표시됩니다.
      </div>
    );
  }

  const placeholder =
    clip.scene_ids.length === 1 ? `장면 ${clip.scene_ids[0]}` : "자동 생성 클립";

  return (
    <div className="flex h-full flex-col gap-5 p-5">
      <Section title="빠른 작업">
        <div className="flex items-center gap-2">
          {editorHref && (
            <Link
              href={editorHref}
              className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-indigo-200 bg-indigo-50 px-3 py-2 text-sm font-medium text-indigo-700 transition-colors hover:bg-indigo-100"
            >
              <PencilIcon />
              편집하기
            </Link>
          )}
          <button
            type="button"
            onClick={onDownload}
            disabled={!onDownload || isDownloading}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-md bg-emerald-500 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-emerald-300"
          >
            <DownloadIcon />
            {isDownloading ? "준비 중..." : "다운로드"}
          </button>
        </div>
      </Section>

      <Section title="제목">
        <TitleInput
          renderJobTitle={renderJobTitle ?? null}
          placeholder={placeholder}
          onSave={onTitleSave}
        />
      </Section>

      <Section title="원본 영상 타임라인">
        <p className="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-xs text-gray-700">
          {formatLongTime(clip.start_ms)} ~ {formatLongTime(clip.end_ms)}
        </p>
      </Section>

      <Section title="스크립트" className="flex-1 min-h-0 overflow-y-auto">
        <ScriptPanel clip={clip} scenes={scenes} />
      </Section>
    </div>
  );
}

interface SectionProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

function Section({ title, children, className }: SectionProps) {
  return (
    <section className={className}>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        {title}
      </h3>
      {children}
    </section>
  );
}

function formatLongTime(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}분 ${String(s).padStart(2, "0")}초`;
}

function PencilIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.6}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.687a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.6}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  );
}

interface TitleInputProps {
  renderJobTitle: string | null;
  placeholder: string;
  onSave?: (title: string | null) => Promise<void> | void;
}

/**
 * Controlled title input that saves on blur. Three visual states:
 *   - **disabled**: no render-job exists yet for this clip. The
 *     placeholder displays a derived label ("장면 ..." or "자동 생성
 *     클립"); user is directed to download first via the tooltip.
 *   - **idle**: editable, no pending save.
 *   - **saving**: blur fired, awaiting server. Briefly shows
 *     "저장 중..." to confirm the action registered.
 *
 * Optimistic update lives in the hook (``useCandidateRenderJobs``);
 * this component just owns the in-flight controlled value so typing
 * doesn't lag behind the server round trip.
 */
function TitleInput({ renderJobTitle, placeholder, onSave }: TitleInputProps) {
  const isEditable = onSave !== undefined;
  // Local controlled value — initialized from the server's current
  // title. Resets when the underlying renderJobTitle changes (e.g.,
  // user switched between candidate cards).
  const [draft, setDraft] = useState<string>(renderJobTitle ?? "");
  const [savingState, setSavingState] = useState<"idle" | "saving">("idle");

  useEffect(() => {
    setDraft(renderJobTitle ?? "");
  }, [renderJobTitle]);

  const persisted = renderJobTitle ?? "";
  const dirty = draft !== persisted;

  const persistDraft = async () => {
    if (!isEditable || !dirty || !onSave) return;
    setSavingState("saving");
    try {
      // Empty string normalizes to null on the server (clears title);
      // pass through as-is and let the API handle it. Trim once at
      // the boundary so leading/trailing whitespace doesn't survive.
      const trimmed = draft.trim();
      await onSave(trimmed === "" ? null : trimmed);
    } finally {
      setSavingState("idle");
    }
  };

  if (!isEditable) {
    return (
      <input
        type="text"
        readOnly
        value={persisted || placeholder}
        aria-readonly="true"
        title="쇼츠를 먼저 렌더링하면 제목을 변경할 수 있어요"
        className="w-full cursor-not-allowed rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700"
      />
    );
  }

  return (
    <div className="space-y-1">
      <input
        type="text"
        value={draft}
        placeholder={placeholder}
        maxLength={255}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          void persistDraft();
        }}
        onKeyDown={(e) => {
          // Enter → save and blur. Calling persistDraft directly (rather
          // than relying on .blur() to propagate the same path) keeps
          // jsdom-based tests deterministic — programmatic blur in jsdom
          // doesn't always fire the React onBlur handler before assertions.
          if (e.key === "Enter") {
            void persistDraft();
            (e.target as HTMLInputElement).blur();
          }
        }}
        aria-label="쇼츠 제목"
        className={cn(
          "w-full rounded-md border bg-white px-3 py-2 text-sm text-gray-900 transition-colors",
          "border-gray-200 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400",
          savingState === "saving" && "opacity-70",
        )}
      />
      <p
        className="text-[10px] text-gray-400"
        aria-live="polite"
      >
        {savingState === "saving"
          ? "저장 중..."
          : dirty
            ? "포커스 해제 시 자동 저장됩니다"
            : " "}
      </p>
    </div>
  );
}
