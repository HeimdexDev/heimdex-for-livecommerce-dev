"use client";

import Link from "next/link";

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
}

/**
 * Right-rail inspector for the active clip.
 *
 * Sections (top to bottom):
 *   1. Quick actions — 편집하기 (deep link to editor) + 다운로드 (mirrors
 *      the card's button so the user has a primary action without
 *      hunting back to the list).
 *   2. 제목 — read-only Phase 1. Title editing is on the roadmap; the
 *      input is kept disabled with an explanatory tooltip rather than
 *      hidden so the surface area stays stable for Phase 3.
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
}: InspectorPanelProps) {
  if (!clip) {
    return (
      <div className="p-6 text-sm text-gray-400">
        클립을 선택하면 자세한 정보가 표시됩니다.
      </div>
    );
  }

  const title = clip.scene_ids.length === 1 ? `장면 ${clip.scene_ids[0]}` : "자동 생성 클립";

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
        <input
          type="text"
          readOnly
          value={title}
          aria-readonly="true"
          title="제목 편집은 곧 지원됩니다"
          className="w-full cursor-not-allowed rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700"
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
