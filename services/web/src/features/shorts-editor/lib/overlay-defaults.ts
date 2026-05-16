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
    fontColor: "#FFFFFF",
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
}): EditorBackgroundOverlay {
  return {
    kind: "background",
    id: generateOverlayId("bg"),
    startMs: args.startMs,
    endMs: args.endMs ?? args.startMs + DEFAULT_OVERLAY_DURATION_MS,
    layerIndex: args.layerIndex ?? 0,
    transform: {
      ...DEFAULT_TRANSFORM,
      widthPx: DEFAULT_BG_WIDTH_PX,
      heightPx: DEFAULT_BG_HEIGHT_PX,
    },
    effects: { ...DEFAULT_EFFECTS },
    fillColor: "#000000",
  };
}
