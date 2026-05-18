/**
 * Default factories for V2 overlays.
 *
 * Used by the reducer when adding a new overlay (Add Text / Add Background
 * buttons) and by tests as fixture seeds. Returned objects pass round-trip
 * validation against contracts 0.12.0 — keep them aligned.
 */

import type {
  EditorBackgroundOverlay,
  EditorTextOverlay,
  EffectsProps,
  TransformProps,
} from "./overlay-types";

let _overlayCounter = 0;
export function generateOverlayId(prefix: "text" | "bg" = "text"): string {
  return `ov_${prefix}_${Date.now()}_${++_overlayCounter}`;
}

export const DEFAULT_OVERLAY_DURATION_MS = 3000;

// ---------------------------------------------------------------------------
// Sub-component defaults
// ---------------------------------------------------------------------------

export const DEFAULT_TRANSFORM: TransformProps = {
  x: 0.5,
  y: 0.5,
  rotationDeg: 0,
  widthPx: null,
  heightPx: null,
};

export const DEFAULT_EFFECTS: EffectsProps = {
  opacity: 1.0,
  stroke: null,
  shadow: null,
};

// ---------------------------------------------------------------------------
// TextOverlay default
// ---------------------------------------------------------------------------

export function createDefaultTextOverlay(args: {
  startMs: number;
  endMs?: number;
  layerIndex?: number;
}): EditorTextOverlay {
  return {
    kind: "text",
    id: generateOverlayId("text"),
    startMs: args.startMs,
    endMs: args.endMs ?? args.startMs + DEFAULT_OVERLAY_DURATION_MS,
    layerIndex: args.layerIndex ?? 0,
    transform: { ...DEFAULT_TRANSFORM, y: 0.85 }, // legacy subtitle baseline
    effects: { ...DEFAULT_EFFECTS },
    text: "",
    fontFamily: "Pretendard",
    fontSizePx: 36,
    fontWeight: 400,
    italic: false,
    underline: false,
    // Black default reads better against bright livecommerce frames
    // (2026-05-18 review).
    fontColor: "#000000",
    textAlign: "center",
    lineHeight: 1.3,
    letterSpacing: 0,
    highlightColor: null,
    highlightPaddingPx: 8,
    highlightOpacity: 1.0,
  };
}

// ---------------------------------------------------------------------------
// BackgroundOverlay default
// ---------------------------------------------------------------------------

const DEFAULT_BG_WIDTH_PX = 240;
const DEFAULT_BG_HEIGHT_PX = 80;

export function createDefaultBackgroundOverlay(args: {
  startMs: number;
  endMs?: number;
  layerIndex?: number;
  // ActionBar (figma 1602:40004 배경 섹션) 의 단색 배경 추가 버튼이
  // 색상 팔레트에서 고른 hex 를 전달한다. 미지정 시 기본값 #000000.
  fillColor?: string;
  // Image source — the "insert image" path reads a file as a data URL
  // and seeds it here so the new background overlay carries the image.
  imageUrl?: string;
}): EditorBackgroundOverlay {
  // Image inserts default to a larger canvas so the picked photo gets
  // an immediately visible footprint instead of being squeezed into the
  // 240×80 solid-color rectangle. Solid color inserts keep the legacy
  // dimensions so existing flows don't shift.
  const isImage = !!args.imageUrl;
  return {
    kind: "background",
    id: generateOverlayId("bg"),
    startMs: args.startMs,
    endMs: args.endMs ?? args.startMs + DEFAULT_OVERLAY_DURATION_MS,
    layerIndex: args.layerIndex ?? 0,
    transform: {
      ...DEFAULT_TRANSFORM,
      widthPx: isImage ? 480 : DEFAULT_BG_WIDTH_PX,
      heightPx: isImage ? 480 : DEFAULT_BG_HEIGHT_PX,
    },
    effects: { ...DEFAULT_EFFECTS },
    // Images render on top of a transparent fill by default so the
    // picture isn't tinted by an accidental black backing.
    fillColor: args.fillColor ?? (isImage ? "transparent" : "#000000"),
    imageUrl: args.imageUrl ?? null,
  };
}
