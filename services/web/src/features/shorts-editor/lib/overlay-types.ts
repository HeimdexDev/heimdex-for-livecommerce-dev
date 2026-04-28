/**
 * V2 overlay types — TypeScript mirror of contracts 0.12.0 OverlaySpec.
 *
 * Field names use camelCase here; the wire format uses snake_case (handled
 * by composition-builder's serializer). When contracts adds a field,
 * mirror it here too — there's no codegen.
 *
 * Discriminator on `kind` matches the Pydantic union in contracts.
 */

// ---------------------------------------------------------------------------
// Editor (camelCase) shape — what the reducer + UI consume
// ---------------------------------------------------------------------------

export interface TransformProps {
  x: number; // normalized [0, 1]
  y: number; // normalized [0, 1]
  rotationDeg: number; // [-360, 360]
  widthPx: number | null; // text auto-sizes; backgrounds require non-null
  heightPx: number | null;
}

export interface StrokeProps {
  color: string; // hex
  widthPx: number; // [0, 50]
}

export interface ShadowProps {
  color: string; // hex
  offsetX: number; // [-100, 100]
  offsetY: number;
  blurPx: number; // [0, 200]
  spreadPx: number; // [0, 100]
}

export interface EffectsProps {
  opacity: number; // [0, 1]
  stroke: StrokeProps | null;
  shadow: ShadowProps | null;
}

export interface EditorTextOverlay {
  kind: "text";
  id: string;
  startMs: number;
  endMs: number;
  layerIndex: number;

  transform: TransformProps;
  effects: EffectsProps;

  text: string;

  fontFamily: "Pretendard" | "Noto Sans KR";
  fontSizePx: number; // [8, 200]
  fontWeight: number; // [100, 900]
  italic: boolean;
  underline: boolean;
  fontColor: string;

  textAlign: "left" | "center" | "right";
  lineHeight: number; // [0.5, 3.0]
  letterSpacing: number; // [-5, 20]

  // Text-fitted highlight (the legacy backgroundColor moved here so a text
  // overlay can have a pill background WITHOUT being a separate background
  // overlay).
  highlightColor: string | null;
  highlightPaddingPx: number;
  highlightOpacity: number;
}

export interface EditorBackgroundOverlay {
  kind: "background";
  id: string;
  startMs: number;
  endMs: number;
  layerIndex: number;

  transform: TransformProps; // widthPx + heightPx required (validated in builder)
  effects: EffectsProps;

  fillColor: string;
}

export type EditorOverlay = EditorTextOverlay | EditorBackgroundOverlay;
export type EditorOverlayKind = EditorOverlay["kind"];

// ---------------------------------------------------------------------------
// Wire format (snake_case) — matches contracts 0.12.0 OverlaySpec
// ---------------------------------------------------------------------------

export interface WireTransform {
  x: number;
  y: number;
  rotation_deg: number;
  width_px: number | null;
  height_px: number | null;
}

export interface WireStroke {
  color: string;
  width_px: number;
}

export interface WireShadow {
  color: string;
  offset_x: number;
  offset_y: number;
  blur_px: number;
  spread_px: number;
}

export interface WireEffects {
  opacity: number;
  stroke: WireStroke | null;
  shadow: WireShadow | null;
}

export interface WireTextOverlay {
  kind: "text";
  id: string;
  start_ms: number;
  end_ms: number;
  layer_index: number;
  transform: WireTransform;
  effects: WireEffects;
  text: string;
  font_family: "Pretendard" | "Noto Sans KR";
  font_size_px: number;
  font_weight: number;
  italic: boolean;
  underline: boolean;
  font_color: string;
  text_align: "left" | "center" | "right";
  line_height: number;
  letter_spacing: number;
  highlight_color: string | null;
  highlight_padding_px: number;
  highlight_opacity: number;
}

export interface WireBackgroundOverlay {
  kind: "background";
  id: string;
  start_ms: number;
  end_ms: number;
  layer_index: number;
  transform: WireTransform;
  effects: WireEffects;
  fill_color: string;
}

export type WireOverlay = WireTextOverlay | WireBackgroundOverlay;

// ---------------------------------------------------------------------------
// Preset wire types (matches services/api/app/modules/subtitle_presets/schemas.py)
// ---------------------------------------------------------------------------

export type PresetKind = "text" | "background";

export interface WirePreset {
  id: string;
  org_id: string;
  user_id: string;
  name: string;
  kind: PresetKind;
  // Style fragment — text overlay style fields without identity (id, kind,
  // start_ms, end_ms, layer_index, transform). Apply-preset on the frontend
  // merges these into an overlay; position + timing are preserved.
  style_json: Record<string, unknown>;
  is_shared: boolean;
  is_owned: boolean;
  created_at: string;
  updated_at: string;
}

export interface WirePresetListResponse {
  items: WirePreset[];
  total: number;
}

