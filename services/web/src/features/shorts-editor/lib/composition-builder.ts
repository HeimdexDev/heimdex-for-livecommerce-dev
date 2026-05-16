import type { EditorState, CompositionSpec } from "./types";
import type {
  EditorBackgroundOverlay,
  EditorTextOverlay,
  WireBackgroundOverlay,
  WireOverlay,
  WireTextOverlay,
} from "./overlay-types";
import { DEFAULT_OUTPUT } from "../constants";

/**
 * Build a CompositionSpec dict from the editor state.
 * Mirrors the highlight_reel service's build_composition_dict() pattern.
 */
export function buildCompositionSpec(
  state: EditorState,
  title?: string | null,
): CompositionSpec {
  return {
    output: { ...DEFAULT_OUTPUT },
    scene_clips: state.clips.map((clip) => ({
      scene_id: clip.sceneId,
      video_id: clip.videoId,
      source_type: clip.sourceType,
      start_ms: clip.trimStartMs,
      end_ms: clip.trimEndMs,
      timeline_start_ms: clip.timelineStartMs,
      volume: clip.volume,
      crop_x: 0.0,
      crop_y: 0.0,
      crop_w: 1.0,
      crop_h: 1.0,
    })),
    subtitles: state.subtitles.map((sub) => ({
      text: sub.text,
      start_ms: sub.startMs,
      end_ms: sub.endMs,
      style: {
        font_family: sub.style.fontFamily,
        font_size_px: sub.style.fontSizePx,
        font_color: sub.style.fontColor,
        font_weight: sub.style.fontWeight,
        position_x: sub.style.positionX,
        position_y: sub.style.positionY,
        background_color: sub.style.backgroundColor,
        background_opacity: sub.style.backgroundOpacity,
      },
    })),
    overlays: state.overlays.map(serializeOverlay),
    transitions: [],
    title: title ?? null,
    version: 1,
  };
}

// ---------------------------------------------------------------------------
// V2 overlay serialization (camelCase → snake_case wire format)
// ---------------------------------------------------------------------------

function serializeOverlay(overlay: EditorTextOverlay | EditorBackgroundOverlay): WireOverlay {
  if (overlay.kind === "text") {
    return serializeTextOverlay(overlay);
  }
  return serializeBackgroundOverlay(overlay);
}

function serializeTextOverlay(o: EditorTextOverlay): WireTextOverlay {
  return {
    kind: "text",
    id: o.id,
    start_ms: o.startMs,
    end_ms: o.endMs,
    layer_index: o.layerIndex,
    transform: {
      x: o.transform.x,
      y: o.transform.y,
      rotation_deg: o.transform.rotationDeg,
      width_px: o.transform.widthPx,
      height_px: o.transform.heightPx,
    },
    effects: {
      opacity: o.effects.opacity,
      stroke: o.effects.stroke
        ? { color: o.effects.stroke.color, width_px: o.effects.stroke.widthPx }
        : null,
      shadow: o.effects.shadow
        ? {
            color: o.effects.shadow.color,
            offset_x: o.effects.shadow.offsetX,
            offset_y: o.effects.shadow.offsetY,
            blur_px: o.effects.shadow.blurPx,
            spread_px: o.effects.shadow.spreadPx,
          }
        : null,
    },
    text: o.text,
    font_family: o.fontFamily,
    font_size_px: o.fontSizePx,
    font_weight: o.fontWeight,
    italic: o.italic,
    underline: o.underline,
    font_color: o.fontColor,
    text_align: o.textAlign,
    line_height: o.lineHeight,
    letter_spacing: o.letterSpacing,
    highlight_color: o.highlightColor,
    highlight_padding_px: o.highlightPaddingPx,
    highlight_opacity: o.highlightOpacity,
  };
}

function serializeBackgroundOverlay(o: EditorBackgroundOverlay): WireBackgroundOverlay {
  return {
    kind: "background",
    id: o.id,
    start_ms: o.startMs,
    end_ms: o.endMs,
    layer_index: o.layerIndex,
    transform: {
      x: o.transform.x,
      y: o.transform.y,
      rotation_deg: o.transform.rotationDeg,
      width_px: o.transform.widthPx,
      height_px: o.transform.heightPx,
    },
    effects: {
      opacity: o.effects.opacity,
      stroke: o.effects.stroke
        ? { color: o.effects.stroke.color, width_px: o.effects.stroke.widthPx }
        : null,
      shadow: o.effects.shadow
        ? {
            color: o.effects.shadow.color,
            offset_x: o.effects.shadow.offsetX,
            offset_y: o.effects.shadow.offsetY,
            blur_px: o.effects.shadow.blurPx,
            spread_px: o.effects.shadow.spreadPx,
          }
        : null,
    },
    fill_color: o.fillColor,
  };
}
