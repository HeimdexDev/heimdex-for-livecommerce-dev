// ============================================================================
// Helpers for the page-level "global style" applied across every cue in
// an auto-shorts edit-clips session.
//
// v1 strategy (locked Decision #1 in
// .claude/plans/edit-clips-right-panel-tabs.md): persist the global style
// by writing the same SubtitleStyleSpec into every cue's ``style`` field
// at PATCH time. Renderer already consumes per-cue style. Whisper-still-
// running cues are protected by ``refinement_source='manual_edit'`` once
// any save lands.
//
// Pure module — no React, no API calls, no I/O. Drift guard test in
// ``__tests__/global-style.test.ts`` keeps every helper anchored to the
// renderer-respected field set from contracts ``SubtitleStyleSpec``.
// ============================================================================

import type { SubtitleEdit } from "@/lib/api/highlight-reel";
import {
  DEFAULT_CANVAS_HEIGHT,
  buildAutoShortsSubtitleStyle,
  type SubtitleStyleSnapshot,
} from "@/lib/subtitle-layout";

// Renderer-respected fields only (Decision #2). Rotation / shadow blur /
// shadow spread / italic / underline / horizontal flip are absent on
// purpose — the FFmpeg drawtext renderer would ignore them, producing a
// WYSIWYG lie.
export interface SubtitleStyleDraft {
  font_family: "Pretendard" | "Noto Sans KR";
  font_size_px: number;
  font_color: string;
  font_weight: number;
  text_align: "left" | "center" | "right";
  position_x: number;
  position_y: number;
  background_color: string | null;
  background_padding: number;
  background_opacity: number;
  stroke_color: string | null;
  stroke_width: number;
  shadow_enabled: boolean;
  shadow_color: string | null;
  shadow_offset_x: number;
  shadow_offset_y: number;
}

/**
 * Default applied when no cue carries an explicit style. Pulls from the
 * auto-shorts layout module so the FE matches what the worker would emit
 * post-render.
 */
export function makeDefaultStyle(): SubtitleStyleDraft {
  const fromLayout: SubtitleStyleSnapshot = buildAutoShortsSubtitleStyle(
    DEFAULT_CANVAS_HEIGHT,
  );
  return {
    font_family: "Pretendard",
    font_size_px: fromLayout.font_size_px,
    font_color: fromLayout.font_color,
    font_weight: fromLayout.font_weight,
    text_align: "center",
    position_x: 0.5,
    position_y: fromLayout.position_y,
    background_color: fromLayout.background_color,
    background_padding: fromLayout.background_padding,
    background_opacity: fromLayout.background_opacity,
    stroke_color: null,
    stroke_width: 0,
    shadow_enabled: true,
    shadow_color: null,
    shadow_offset_x: 0,
    shadow_offset_y: 2,
  };
}

/**
 * Try to extract a single ``SubtitleStyleDraft`` from a list of cues.
 * Returns ``null`` when:
 *   - the cues list is empty
 *   - cues have mixed styles (UI surfaces a "혼합됨" indicator + an
 *     "Apply globally" affordance)
 *
 * Mixed = any cue's style serializes to a different JSON string than the
 * first cue's style. JSON.stringify is stable for our flat field set
 * (no nested objects) so this comparison is safe.
 */
export function deriveGlobalStyle(
  cues: SubtitleEdit[],
): SubtitleStyleDraft | null {
  if (cues.length === 0) return null;
  const first = readStyleFromCue(cues[0]);
  if (!first) return null;
  const firstSerialized = serialize(first);
  for (let i = 1; i < cues.length; i++) {
    const next = readStyleFromCue(cues[i]);
    if (!next) return null;
    if (serialize(next) !== firstSerialized) return null;
  }
  return first;
}

/**
 * Apply a single style across every cue. Returns a fresh array; original
 * cue objects are unchanged. The ``style`` field is replaced wholesale
 * (no merge with the cue's existing style) so the operator's intent is
 * unambiguous.
 */
export function applyGlobalStyleToCues(
  cues: SubtitleEdit[],
  style: SubtitleStyleDraft,
): SubtitleEdit[] {
  const serialized = styleToRecord(style);
  return cues.map((cue) => ({
    ...cue,
    style: serialized,
  }));
}

/**
 * Merge a partial update into a base style. Falls back to ``makeDefaultStyle``
 * fields for keys the caller doesn't supply.
 */
export function mergeStyle(
  base: SubtitleStyleDraft,
  partial: Partial<SubtitleStyleDraft>,
): SubtitleStyleDraft {
  return { ...base, ...partial };
}

// ----------------------------------------------------------------------
// Internal helpers
// ----------------------------------------------------------------------

function readStyleFromCue(cue: SubtitleEdit): SubtitleStyleDraft | null {
  const raw = cue.style;
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const family = readEnum(r.font_family, ["Pretendard", "Noto Sans KR"]);
  const align = readEnum(r.text_align, ["left", "center", "right"]);
  if (!family || !align) return null;
  const size = readNumber(r.font_size_px);
  const color = readString(r.font_color);
  const weight = readNumber(r.font_weight);
  const posX = readNumber(r.position_x);
  const posY = readNumber(r.position_y);
  const bgColor = readNullableString(r.background_color);
  const bgPad = readNumber(r.background_padding);
  const bgOp = readNumber(r.background_opacity);
  const strokeColor = readNullableString(r.stroke_color);
  const strokeWidth = readNumber(r.stroke_width);
  const shadowEnabled = readBoolean(r.shadow_enabled);
  const shadowColor = readNullableString(r.shadow_color);
  const shadowX = readNumber(r.shadow_offset_x);
  const shadowY = readNumber(r.shadow_offset_y);
  if (
    size === null ||
    color === null ||
    weight === null ||
    posX === null ||
    posY === null ||
    bgPad === null ||
    bgOp === null ||
    strokeWidth === null ||
    shadowEnabled === null ||
    shadowX === null ||
    shadowY === null
  ) {
    return null;
  }
  return {
    font_family: family,
    font_size_px: size,
    font_color: color,
    font_weight: weight,
    text_align: align,
    position_x: posX,
    position_y: posY,
    background_color: bgColor,
    background_padding: bgPad,
    background_opacity: bgOp,
    stroke_color: strokeColor,
    stroke_width: strokeWidth,
    shadow_enabled: shadowEnabled,
    shadow_color: shadowColor,
    shadow_offset_x: shadowX,
    shadow_offset_y: shadowY,
  };
}

function styleToRecord(style: SubtitleStyleDraft): Record<string, unknown> {
  // Object.assign keeps key order stable for the serialize() drift guard.
  return { ...style };
}

function serialize(style: SubtitleStyleDraft): string {
  const ordered: Array<[string, unknown]> = [
    ["font_family", style.font_family],
    ["font_size_px", style.font_size_px],
    ["font_color", style.font_color],
    ["font_weight", style.font_weight],
    ["text_align", style.text_align],
    ["position_x", style.position_x],
    ["position_y", style.position_y],
    ["background_color", style.background_color],
    ["background_padding", style.background_padding],
    ["background_opacity", style.background_opacity],
    ["stroke_color", style.stroke_color],
    ["stroke_width", style.stroke_width],
    ["shadow_enabled", style.shadow_enabled],
    ["shadow_color", style.shadow_color],
    ["shadow_offset_x", style.shadow_offset_x],
    ["shadow_offset_y", style.shadow_offset_y],
  ];
  return JSON.stringify(ordered);
}

function readEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
): T | null {
  if (typeof value !== "string") return null;
  return (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function readNullableString(value: unknown): string | null {
  if (value === null) return null;
  if (typeof value === "string") return value;
  return null;
}

function readBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}
