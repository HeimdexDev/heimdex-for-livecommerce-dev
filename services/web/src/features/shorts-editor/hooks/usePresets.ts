"use client";

/**
 * usePresets — backend-backed preset list with optimistic save/delete.
 *
 * Loads on mount, exposes save/rename/delete/applyTo. Errors surface as
 * `error: string | null` for callers to render; the hook does not throw.
 *
 * Tolerant of the API not existing yet (404 / network error during the
 * grace period before PR #90 lands): logs and renders an empty list.
 */

import { useCallback, useEffect, useState } from "react";

import {
  createPreset as apiCreate,
  deletePreset as apiDelete,
  listPresets as apiList,
  PresetRateLimitError,
  updatePreset as apiUpdate,
} from "@/lib/api/subtitle-presets";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
  EditorTextOverlay,
  PresetKind,
  WirePreset,
} from "../lib/overlay-types";

type TokenGetter = () => Promise<string | null>;

interface UsePresetsArgs {
  kind?: PresetKind;
  getToken: TokenGetter;
  enabled?: boolean; // skip network when false (e.g. flag off)
}

export interface PresetsApi {
  presets: WirePreset[];
  isLoading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  save: (
    name: string,
    overlay: EditorOverlay,
    isShared: boolean,
  ) => Promise<WirePreset | null>;
  rename: (presetId: string, name: string) => Promise<void>;
  setShared: (presetId: string, isShared: boolean) => Promise<void>;
  remove: (presetId: string) => Promise<void>;
  applyTo: <O extends EditorOverlay>(
    overlay: O,
    preset: WirePreset,
  ) => O;
}

export function usePresets({
  kind,
  getToken,
  enabled = true,
}: UsePresetsArgs): PresetsApi {
  const [presets, setPresets] = useState<WirePreset[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!enabled) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiList({ kind, limit: 100, offset: 0 }, getToken);
      setPresets(res.items);
    } catch (err) {
      // Endpoint may not be deployed yet (PR #90 in flight). Log + degrade
      // to empty rather than blocking the panel from rendering.
      // eslint-disable-next-line no-console
      console.warn("usePresets.reload failed", err);
      setError(err instanceof Error ? err.message : "프리셋을 불러올 수 없습니다.");
      setPresets([]);
    } finally {
      setIsLoading(false);
    }
  }, [enabled, kind, getToken]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(
    async (name: string, overlay: EditorOverlay, isShared: boolean) => {
      try {
        const styleJson = extractStyleFragment(overlay);
        const created = await apiCreate(
          {
            name,
            kind: overlay.kind,
            style_json: styleJson,
            is_shared: isShared,
          },
          getToken,
        );
        // Prepend so the latest preset shows at the top of the dropdown.
        setPresets((prev) => [created, ...prev]);
        return created;
      } catch (err) {
        if (err instanceof PresetRateLimitError) {
          setError(err.message);
        } else {
          setError(err instanceof Error ? err.message : "프리셋 저장 실패");
        }
        return null;
      }
    },
    [getToken],
  );

  const rename = useCallback(
    async (presetId: string, name: string) => {
      try {
        const updated = await apiUpdate(presetId, { name }, getToken);
        setPresets((prev) => prev.map((p) => (p.id === presetId ? updated : p)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "이름 변경 실패");
      }
    },
    [getToken],
  );

  const setShared = useCallback(
    async (presetId: string, isShared: boolean) => {
      try {
        const updated = await apiUpdate(
          presetId,
          { is_shared: isShared },
          getToken,
        );
        setPresets((prev) => prev.map((p) => (p.id === presetId ? updated : p)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "공유 변경 실패");
      }
    },
    [getToken],
  );

  const remove = useCallback(
    async (presetId: string) => {
      // Optimistic removal — the API returns 204 on success and we won't
      // need the row back. On failure, refetch.
      const previous = presets;
      setPresets((prev) => prev.filter((p) => p.id !== presetId));
      try {
        await apiDelete(presetId, getToken);
      } catch (err) {
        setError(err instanceof Error ? err.message : "프리셋 삭제 실패");
        setPresets(previous);
      }
    },
    [getToken, presets],
  );

  const applyTo = useCallback(
    <O extends EditorOverlay>(overlay: O, preset: WirePreset): O => {
      // Apply preset = merge style fields, preserve identity (id, kind,
      // start/end, layer_index, transform). Preset.style_json was stripped
      // of identity at write time by services/api/.../subtitle_presets/schemas.py.
      const styleFields = preset.style_json as Record<string, unknown>;
      return mergeStyleFragment(overlay, styleFields);
    },
    [],
  );

  return {
    presets,
    isLoading,
    error,
    reload,
    save,
    rename,
    setShared,
    remove,
    applyTo,
  };
}

// ---------------------------------------------------------------------------
// Style fragment extract / merge (camelCase domain ↔ snake_case wire)
// ---------------------------------------------------------------------------

/**
 * Extract the *style* slice of an overlay (no identity, no timing, no
 * position) in wire format. The API performs the same shape validation
 * server-side via _validate_style_json.
 */
function extractStyleFragment(overlay: EditorOverlay): Record<string, unknown> {
  if (overlay.kind === "text") {
    return extractTextStyle(overlay);
  }
  return extractBackgroundStyle(overlay);
}

function extractTextStyle(o: EditorTextOverlay): Record<string, unknown> {
  return {
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
    effects: serializeEffects(o.effects),
  };
}

function extractBackgroundStyle(
  o: EditorBackgroundOverlay,
): Record<string, unknown> {
  return {
    fill_color: o.fillColor,
    effects: serializeEffects(o.effects),
  };
}

function serializeEffects(
  e: EditorOverlay["effects"],
): Record<string, unknown> {
  return {
    opacity: e.opacity,
    stroke: e.stroke
      ? { color: e.stroke.color, width_px: e.stroke.widthPx }
      : null,
    shadow: e.shadow
      ? {
          color: e.shadow.color,
          offset_x: e.shadow.offsetX,
          offset_y: e.shadow.offsetY,
          blur_px: e.shadow.blurPx,
          spread_px: e.shadow.spreadPx,
        }
      : null,
  };
}

function mergeStyleFragment<O extends EditorOverlay>(
  overlay: O,
  style: Record<string, unknown>,
): O {
  if (overlay.kind === "text") {
    return mergeTextStyle(overlay, style) as O;
  }
  return mergeBackgroundStyle(
    overlay as EditorBackgroundOverlay,
    style,
  ) as O;
}

function mergeTextStyle(
  base: EditorTextOverlay,
  style: Record<string, unknown>,
): EditorTextOverlay {
  return {
    ...base,
    text: getString(style, "text", base.text),
    fontFamily: getString(style, "font_family", base.fontFamily) as
      | "Pretendard"
      | "Noto Sans KR",
    fontSizePx: getNumber(style, "font_size_px", base.fontSizePx),
    fontWeight: getNumber(style, "font_weight", base.fontWeight),
    italic: getBool(style, "italic", base.italic),
    underline: getBool(style, "underline", base.underline),
    fontColor: getString(style, "font_color", base.fontColor),
    textAlign: (getString(style, "text_align", base.textAlign) as
      | "left"
      | "center"
      | "right"),
    lineHeight: getNumber(style, "line_height", base.lineHeight),
    letterSpacing: getNumber(style, "letter_spacing", base.letterSpacing),
    highlightColor:
      style["highlight_color"] === null
        ? null
        : getString(style, "highlight_color", base.highlightColor ?? "") || null,
    highlightPaddingPx: getNumber(
      style,
      "highlight_padding_px",
      base.highlightPaddingPx,
    ),
    highlightOpacity: getNumber(
      style,
      "highlight_opacity",
      base.highlightOpacity,
    ),
    effects: parseEffects(style["effects"], base.effects),
  };
}

function mergeBackgroundStyle(
  base: EditorBackgroundOverlay,
  style: Record<string, unknown>,
): EditorBackgroundOverlay {
  return {
    ...base,
    fillColor: getString(style, "fill_color", base.fillColor),
    effects: parseEffects(style["effects"], base.effects),
  };
}

function parseEffects(
  raw: unknown,
  fallback: EditorOverlay["effects"],
): EditorOverlay["effects"] {
  if (!raw || typeof raw !== "object") return fallback;
  const e = raw as Record<string, unknown>;
  const stroke = e["stroke"] as Record<string, unknown> | null | undefined;
  const shadow = e["shadow"] as Record<string, unknown> | null | undefined;
  return {
    opacity: typeof e["opacity"] === "number" ? e["opacity"] : fallback.opacity,
    stroke: stroke
      ? {
          color: typeof stroke["color"] === "string" ? stroke["color"] : "#000000",
          widthPx: typeof stroke["width_px"] === "number" ? stroke["width_px"] : 1,
        }
      : null,
    shadow: shadow
      ? {
          color: typeof shadow["color"] === "string" ? shadow["color"] : "#000000",
          offsetX: typeof shadow["offset_x"] === "number" ? shadow["offset_x"] : 0,
          offsetY: typeof shadow["offset_y"] === "number" ? shadow["offset_y"] : 4,
          blurPx: typeof shadow["blur_px"] === "number" ? shadow["blur_px"] : 0,
          spreadPx:
            typeof shadow["spread_px"] === "number" ? shadow["spread_px"] : 0,
        }
      : null,
  };
}

function getString(
  obj: Record<string, unknown>,
  key: string,
  fallback: string,
): string {
  const v = obj[key];
  return typeof v === "string" ? v : fallback;
}

function getNumber(
  obj: Record<string, unknown>,
  key: string,
  fallback: number,
): number {
  const v = obj[key];
  return typeof v === "number" ? v : fallback;
}

function getBool(
  obj: Record<string, unknown>,
  key: string,
  fallback: boolean,
): boolean {
  const v = obj[key];
  return typeof v === "boolean" ? v : fallback;
}
