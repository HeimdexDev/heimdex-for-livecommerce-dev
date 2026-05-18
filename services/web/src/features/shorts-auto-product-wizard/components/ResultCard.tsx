// figma 1699:252725 (단일 상품) + 1699:252759 (다수 상품, +N 오버플로우)
//
// Card layout — total 287 × 253, no shadow, border-neutral-100 rounded-10:
//
//   ┌─[thumbnail w-150 h-253]─┬─[right column flex-1 px-12 py-16]─────┐
//   │  product chip(s) at     │ 쇼츠 N             (14px semibold)    │
//   │  bottom-left (8px       │                                       │
//   │  inset), up to 2 +      │ 쇼츠 길이    1분 32초                   │
//   │  "+N" overflow chip     │ 진행률       100%                       │
//   │                         │                                       │
//   │                         │ 요약 캡션 … (12px medium neutral-800)  │
//   │                         │                       [상태 chip]      │
//   └─────────────────────────┴───────────────────────────────────────┘

"use client";

import { useEffect, useState } from "react";

import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";
import { getAgentThumbnailUrl, getCloudThumbnailUrl } from "@/lib/agent";
import { getRenderJob } from "@/lib/api/shorts-render";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

import {
  ResultStatusChip,
  deriveResultChipState,
} from "./ResultStatusChip";
import { ResultCardMenu } from "./ResultCardMenu";

interface Props {
  child: JobStatusResponse;
  /** Parent video_id — feeds the thumbnail loader. */
  videoId: string;
  /** 1-based ordinal shown as "쇼츠 N". Falls back to ``shorts_index + 1``. */
  ordinal: number;
  /** Original criteria.length_seconds for the parent scan order. */
  lengthSeconds?: number | null;
  /**
   * Selected-product labels for this child. The thumbnail surfaces up to
   * two as bottom-left chips; the third+ collapse into a single "+N"
   * overflow chip (figma 1699:252759).
   */
  productLabels?: string[];
  // figma 1699:252790 — 우측 컬럼 요약 텍스트. 50자(공백 포함) 초과 시 truncate.
  summary?: string | null;
  /**
   * Custom title set by the user via the "제목 변경" menu entry. When
   * present, replaces the default "쇼츠 {ordinal}" headline so the
   * operator's chosen label sticks.
   */
  title?: string | null;
  onRename: () => void;
  onSave?: () => void;
  onExport?: () => void;
  onCancel: () => void;
  onOpenEditor: () => void;
}

const SUMMARY_MAX_CHARS = 50;
// Visible product chips before the row collapses into a "+N" overflow
// chip — matches figma 1699:252759 which shows 2 chips + "+4".
const MAX_VISIBLE_PRODUCT_CHIPS = 2;

function formatLength(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m === 0) return `${s}초`;
  if (s === 0) return `${m}분`;
  return `${m}분 ${s}초`;
}

function truncateSummary(text: string | null | undefined): string {
  if (!text) return "";
  if (text.length <= SUMMARY_MAX_CHARS) return text;
  return `${text.slice(0, SUMMARY_MAX_CHARS)}…`;
}

export function ResultCard({
  child,
  videoId,
  ordinal,
  lengthSeconds,
  productLabels = [],
  summary,
  title,
  onRename,
  onSave,
  onExport,
  onCancel,
  onOpenEditor,
}: Props) {
  const displayTitle = title && title.trim().length > 0 ? title : `쇼츠 ${ordinal}`;
  const state = deriveResultChipState(child);
  const isCompleted = state === "done";
  const rawProgressPct = Math.max(0, Math.min(100, Math.round(child.progress_pct)));
  // Resolve product chip rows: up to MAX_VISIBLE chips plus a single
  // "+N" overflow tag when there are more labels than slots.
  const visibleChips = productLabels.slice(0, MAX_VISIBLE_PRODUCT_CHIPS);
  const overflowCount = Math.max(0, productLabels.length - visibleChips.length);
  // Each render-job carries thumbnail_video_id + thumbnail_scene_id —
  // the backend extracts them from input_spec.scene_clips[0] when the
  // job is created. We fetch the render-job lazily once per card and
  // prefer the cloud thumbnail (presigned S3) so cards render even
  // when no local agent is reachable. Fallback chain: cloud → agent
  // → dark placeholder.
  const { getAccessToken } = useAuth();
  const [thumbScene, setThumbScene] = useState<{
    videoId: string;
    sceneId: string;
  } | null>(null);
  const [thumbStage, setThumbStage] = useState<"cloud" | "agent" | "placeholder">("cloud");
  const [renderSummary, setRenderSummary] = useState<string | null>(null);

  useEffect(() => {
    if (!child.render_job_id) return;
    let cancelled = false;
    void (async () => {
      try {
        const job = await getRenderJob(
          child.render_job_id as string,
          getAccessToken,
        );
        if (cancelled) return;
        if (job.thumbnail_video_id && job.thumbnail_scene_id) {
          setThumbScene({
            videoId: job.thumbnail_video_id,
            sceneId: job.thumbnail_scene_id,
          });
        }
        // RenderJobResponse.summary is populated post-render via the
        // summary_service. The wizard's scan-order poll doesn't echo it
        // back, so we read it lazily here and use it as the fallback
        // when ``child.render_summary`` (optimistic field, may be
        // undefined in production) is null.
        if (job.summary) {
          setRenderSummary(job.summary);
        }
      } catch {
        // Card sticks to the agent / placeholder fallback chain.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [child.render_job_id, getAccessToken]);

  const thumbnailSrc = (() => {
    if (thumbStage === "placeholder") return null;
    if (thumbStage === "cloud" && thumbScene) {
      return getCloudThumbnailUrl(thumbScene.videoId, thumbScene.sceneId);
    }
    if (thumbStage === "agent") {
      return getAgentThumbnailUrl(
        thumbScene?.videoId ?? videoId,
        thumbScene?.sceneId,
      );
    }
    // No scene resolved yet — show the parent video's agent keyframe
    // so the card has visual context while the render-job fetch
    // resolves.
    return videoId ? getAgentThumbnailUrl(videoId) : null;
  })();

  const handleThumbError = () => {
    setThumbStage((prev) => (prev === "cloud" ? "agent" : "placeholder"));
  };

  // Summary resolution: prefer the (optimistic) field on the wizard
  // poll response; fall back to the render-job's summary we fetched
  // lazily above. While both are empty, a skeleton placeholder reads
  // "요약 생성 중…" so the row doesn't collapse.
  const resolvedSummary = summary ?? renderSummary;
  const summaryText = truncateSummary(resolvedSummary);

  // 2026-05-18 — gate the displayed 100% on the editor view being
  // fully resolvable: the render must be complete AND we must have a
  // thumbnail scene AND a summary string. Until both arrive we cap at
  // 95% so the bar doesn't claim completion while the card is still
  // hydrating. Pre-completion the backend's own progress_pct drives
  // the display.
  const editorReady =
    isCompleted && thumbScene != null && resolvedSummary != null;
  const progressPct = isCompleted && !editorReady
    ? Math.min(95, rawProgressPct)
    : rawProgressPct;

  return (
    <article
      className="relative flex h-[253px] w-[287px] items-start overflow-clip rounded-card border border-grayscale-100 bg-white"
      data-testid={`result-card-${ordinal}`}
    >
      <button
        type="button"
        onClick={onOpenEditor}
        // Clicking is always allowed (2026-05-18) — operators wanted to
        // open the editor even while the render is still in progress to
        // inspect the source clips. Editor surfaces a "준비 중" state
        // when the render isn't done yet.
        aria-label={isCompleted ? "편집 페이지 열기" : "쇼츠 생성 중 (편집 페이지 열기)"}
        data-testid="result-card-open-editor"
        className="group relative h-full w-[150px] shrink-0 overflow-hidden bg-[#E9E9E9] text-left transition-opacity"
      >
        {/* Neutral #E9E9E9 skeleton — visible until the thumbnail
            resolves so the card never flashes a plain dark block. The
            picture is painted via background-image (not <img>) so a
            broken / 404 URL never renders the browser's default "broken
            image" glyph in the top-left corner. */}
        <div
          aria-hidden
          className="absolute inset-0 animate-pulse bg-[#E9E9E9]"
        />
        {thumbnailSrc ? (
          <ThumbnailImage
            src={thumbnailSrc}
            onError={handleThumbError}
          />
        ) : null}
        {visibleChips.length > 0 || overflowCount > 0 ? (
          <div className="absolute left-[8px] bottom-[8px] z-10 flex items-center gap-[2px]">
            {visibleChips.map((label, i) => (
              <span
                key={`${label}-${i}`}
                className="inline-flex items-center justify-center rounded-[4px] bg-black/50 px-[4px] py-[2px] font-pretendard text-[8px] font-medium text-white"
              >
                {label}
              </span>
            ))}
            {overflowCount > 0 ? (
              <span
                className="inline-flex items-center justify-center rounded-[4px] bg-black/50 px-[4px] py-[2px] font-pretendard text-[8px] font-medium text-white"
                data-testid="result-card-product-overflow"
              >
                +{overflowCount}
              </span>
            ) : null}
          </div>
        ) : null}
        {isCompleted ? (
          <span
            aria-hidden
            className="absolute inset-0 z-0 bg-transparent transition-colors group-hover:bg-black/10"
          />
        ) : null}
      </button>

      <div className="flex h-full flex-1 flex-col items-end gap-[20px] self-stretch px-[12px] py-[16px]">
        {/* Top group: title + stats (label/value pairs) — Figma stacks
            them with a 20px gap inside one flex-col so the spacing
            between header and "쇼츠 길이" stays at exactly 20px. */}
        <div className="flex w-full flex-col items-start gap-[20px]">
          <p
            className="font-pretendard text-[14px] font-semibold tracking-[-0.35px] leading-[1.4] text-grayscale-800 line-clamp-1"
            data-testid="result-card-title"
            title={displayTitle}
          >
            {displayTitle}
          </p>

          <dl className="flex w-full items-start gap-[10px] font-pretendard text-[12px] font-medium leading-[1.4] tracking-[-0.3px]">
            <div className="flex flex-col items-start gap-[10px] text-grayscale-500">
              <dt>쇼츠 길이</dt>
              <dt>진행률</dt>
            </div>
            <div className="flex flex-col items-start gap-[10px] text-grayscale-800">
              <dd>{formatLength(lengthSeconds)}</dd>
              <dd data-testid="result-card-progress">{progressPct}%</dd>
            </div>
          </dl>
        </div>

        {/* Summary takes the remaining space between the stats block and
            the status chip; truncates to 50 chars per Figma. When the
            backend hasn't generated a summary yet we render a quiet
            placeholder so the slot doesn't collapse and the chip
            position stays stable. */}
        <p
          className="flex-1 w-full self-start font-pretendard text-[12px] font-medium leading-[1.4] text-grayscale-800"
          data-testid="result-card-summary"
        >
          {summaryText || (
            <span className="text-grayscale-400">요약 생성 중…</span>
          )}
        </p>

        <ResultStatusChip
          state={state}
          className="shrink-0 self-end"
        />
      </div>

      {/* Dot-3 menu is overlaid at the card's top-right corner so it
          doesn't consume right-column width (figma omits the dedicated
          24px column — the menu is an affordance, not part of the
          rhythm). */}
      <div className="absolute right-[4px] top-[4px] z-20">
        <ResultCardMenu
          isCompleted={isCompleted}
          onRename={onRename}
          onSave={onSave}
          onExport={onExport}
          onCancel={onCancel}
        />
      </div>
    </article>
  );
}

/**
 * Thumbnail painter that uses background-image instead of an <img> tag.
 *
 * Why: when the backing video has no agent-rendered keyframe yet, the
 * URL resolves but returns a non-image / 404, and the browser draws its
 * default "broken image" glyph in the top-left of the box. Painting via
 * background-image makes failures silent — the skeleton underneath
 * stays visible. We still call ``onError`` so the fallback chain
 * (cloud → agent → placeholder) advances exactly like before.
 */
function ThumbnailImage({
  src,
  onError,
}: {
  src: string;
  onError: () => void;
}) {
  return (
    <>
      <div
        aria-hidden
        className="absolute inset-0 bg-cover bg-center bg-no-repeat"
        style={{ backgroundImage: `url(${src})` }}
      />
      {/* Hidden probe <img> drives the onError handoff. ``display:none``
          keeps the broken-image glyph from rendering visibly while the
          load attempt is in flight. */}
      <img
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        onError={onError}
        style={{ display: "none" }}
      />
    </>
  );
}
