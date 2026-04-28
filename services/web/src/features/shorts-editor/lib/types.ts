import type { EditorOverlay, WireOverlay } from "./overlay-types";

// ============================================================================
// Shorts Editor Types
// ============================================================================

export interface EditorClip {
  id: string;
  sceneId: string;
  videoId: string;
  sourceType: string;
  originalStartMs: number;
  originalEndMs: number;
  trimStartMs: number;
  trimEndMs: number;
  timelineStartMs: number;
  volume: number;
  label?: string;
}

export interface SubtitleStyle {
  fontFamily: string;
  fontSizePx: number;
  fontColor: string;
  fontWeight: number;
  positionX: number;
  positionY: number;
  backgroundColor: string | null;
  backgroundOpacity: number;
}

export interface EditorSubtitle {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
  style: SubtitleStyle;
}

export interface EditorState {
  videoId: string;
  sourceType: string;
  clips: EditorClip[];
  subtitles: EditorSubtitle[];
  // V2 overlays — coexist with V1 subtitles. Feature-flag selects which the
  // panel + preview consume; both can be non-empty mid-migration without
  // breaking validation. Backend serializer in composition-builder writes
  // both fields and lets the renderer ignore whichever is empty.
  overlays: EditorOverlay[];
  selectedClipIndex: number | null;
  selectedSubtitleIndex: number | null;
  selectedOverlayId: string | null;
  playheadMs: number;
  isPlaying: boolean;
  totalDurationMs: number;
  zoom: number;
  isDirty: boolean;
}

// ============================================================================
// Actions
// ============================================================================

export type EditorAction =
  | { type: "INIT_FROM_SCENES"; videoId: string; sourceType: string; clips: EditorClip[] }
  | { type: "INIT_FROM_COMPOSITION"; state: Partial<EditorState> }
  | { type: "ADD_CLIP"; clip: EditorClip }
  | { type: "REMOVE_CLIP"; index: number }
  | { type: "REORDER_CLIPS"; fromIndex: number; toIndex: number }
  | { type: "TRIM_CLIP"; index: number; trimStartMs?: number; trimEndMs?: number }
  | { type: "SET_CLIP_VOLUME"; index: number; volume: number }
  | { type: "SELECT_CLIP"; index: number | null }
  | { type: "ADD_SUBTITLE"; subtitle: EditorSubtitle }
  | { type: "UPDATE_SUBTITLE"; index: number; updates: Partial<Omit<EditorSubtitle, "id">> }
  | { type: "REMOVE_SUBTITLE"; index: number }
  | { type: "SELECT_SUBTITLE"; index: number | null }
  // V2 overlay actions (text + background).
  | { type: "ADD_OVERLAY"; overlay: EditorOverlay }
  | { type: "UPDATE_OVERLAY"; id: string; updates: Partial<EditorOverlay> }
  | { type: "REMOVE_OVERLAY"; id: string }
  | { type: "SELECT_OVERLAY"; id: string | null }
  | { type: "REORDER_OVERLAY"; id: string; direction: "front" | "back" | "forward" | "backward" }
  | { type: "SET_PLAYHEAD"; ms: number }
  | { type: "SET_PLAYING"; playing: boolean }
  | { type: "SET_ZOOM"; zoom: number }
  | { type: "MARK_CLEAN" };

// ============================================================================
// CompositionSpec output types (matches backend schema)
// ============================================================================

export interface CompositionOutputSpec {
  width: number;
  height: number;
  fps: number;
  format: "mp4" | "webm";
  background_color: string;
}

export interface CompositionSceneClip {
  scene_id: string;
  video_id: string;
  source_type: string;
  start_ms: number;
  end_ms: number;
  timeline_start_ms: number;
  volume: number;
  crop_x: number;
  crop_y: number;
  crop_w: number;
  crop_h: number;
}

export interface CompositionSubtitleStyle {
  font_family: string;
  font_size_px: number;
  font_color: string;
  font_weight: number;
  position_x: number;
  position_y: number;
  background_color: string | null;
  background_opacity: number;
}

export interface CompositionSubtitle {
  text: string;
  start_ms: number;
  end_ms: number;
  style: CompositionSubtitleStyle;
}

export interface CompositionSpec {
  output: CompositionOutputSpec;
  scene_clips: CompositionSceneClip[];
  subtitles: CompositionSubtitle[];
  // V2 overlays — empty for V1-only compositions; populated by the new editor.
  // The wire shape lives in overlay-types.ts.
  overlays: WireOverlay[];
  transitions: unknown[];
  title: string | null;
  version: number;
}
