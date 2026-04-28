"use client";

import { type CSSProperties, type PointerEventHandler } from "react";

import { resolveFontFamily } from "@/lib/fonts";
import { cn } from "@/lib/utils";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
  EditorTextOverlay,
  EffectsProps,
  ShadowProps,
  TransformProps,
} from "../../lib/overlay-types";

interface OverlayRendererProps {
  overlay: EditorOverlay;
  isSelected: boolean;
  onPointerDown?: PointerEventHandler<HTMLDivElement>;
  onClick?: () => void;
}

/**
 * Renders an EditorOverlay (text or background) as a positioned, styled
 * <div>/<p> in the preview canvas. Pure: no state, no network — caller
 * controls selection + drag.
 *
 * Visual fidelity goal: what the user sees here approximates what the
 * worker bakes via PIL. Differences:
 * - Browser kerning vs PIL kerning will drift slightly. Tracked in plan
 *   as Risk 3 (rendered MP4 may not be pixel-identical to preview).
 * - Stroke is rendered via -webkit-text-stroke (text) or border (bg).
 * - Shadow uses CSS drop-shadow (filter) for the blur+spread approximation.
 */
export function OverlayRenderer({
  overlay,
  isSelected,
  onPointerDown,
  onClick,
}: OverlayRendererProps) {
  if (overlay.kind === "text") {
    return (
      <TextOverlayBox
        overlay={overlay}
        isSelected={isSelected}
        onPointerDown={onPointerDown}
        onClick={onClick}
      />
    );
  }
  return (
    <BackgroundOverlayBox
      overlay={overlay}
      isSelected={isSelected}
      onPointerDown={onPointerDown}
      onClick={onClick}
    />
  );
}

// ---------------------------------------------------------------------------
// Text overlay
// ---------------------------------------------------------------------------

function TextOverlayBox({
  overlay,
  isSelected,
  onPointerDown,
  onClick,
}: {
  overlay: EditorTextOverlay;
  isSelected: boolean;
  onPointerDown?: PointerEventHandler<HTMLDivElement>;
  onClick?: () => void;
}) {
  const containerStyle = positionContainerStyle(overlay.transform, overlay.layerIndex);

  // Effects → CSS. Stroke is approximated via -webkit-text-stroke; opacity
  // is on the wrapper so it composes with shadow/stroke. Shadow uses CSS
  // text-shadow stack (no spread on text — CSS drop-shadow on the wrapper
  // covers spread approximately).
  const textStyle: CSSProperties = {
    fontFamily: resolveFontFamily(overlay.fontFamily),
    fontSize: `${Math.max(8, overlay.fontSizePx * 0.5)}px`,
    fontWeight: overlay.fontWeight,
    fontStyle: overlay.italic ? "italic" : "normal",
    textDecoration: overlay.underline ? "underline" : "none",
    color: overlay.fontColor,
    textAlign: overlay.textAlign,
    lineHeight: overlay.lineHeight,
    letterSpacing: `${overlay.letterSpacing * 0.05}em`,
    padding: "2px 6px",
    borderRadius: "2px",
    whiteSpace: "pre-wrap",
    ...textShadowAndStrokeStyles(overlay.effects),
    ...(overlay.highlightColor
      ? {
          backgroundColor: overlay.highlightColor,
          opacity: overlay.highlightOpacity,
        }
      : {}),
  };

  return (
    <div
      data-overlay-id={overlay.id}
      style={{ ...containerStyle, opacity: overlay.effects.opacity }}
      className={cn(
        "absolute select-none cursor-grab",
        isSelected && "ring-2 ring-indigo-400",
      )}
      onPointerDown={onPointerDown}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
    >
      {overlay.text === "" ? (
        <div
          className="h-12 w-12 rounded bg-red-500/70"
          aria-label="empty text overlay placeholder"
        />
      ) : (
        <p style={textStyle}>{overlay.text}</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background overlay
// ---------------------------------------------------------------------------

function BackgroundOverlayBox({
  overlay,
  isSelected,
  onPointerDown,
  onClick,
}: {
  overlay: EditorBackgroundOverlay;
  isSelected: boolean;
  onPointerDown?: PointerEventHandler<HTMLDivElement>;
  onClick?: () => void;
}) {
  const containerStyle = positionContainerStyle(
    overlay.transform,
    overlay.layerIndex,
  );

  const boxStyle: CSSProperties = {
    width: `${overlay.transform.widthPx ?? 100}px`,
    height: `${overlay.transform.heightPx ?? 60}px`,
    backgroundColor: overlay.fillColor,
    ...(overlay.effects.stroke
      ? {
          outline: `${overlay.effects.stroke.widthPx}px solid ${overlay.effects.stroke.color}`,
          outlineOffset: 0,
        }
      : {}),
    ...(overlay.effects.shadow
      ? {
          boxShadow: cssBoxShadow(overlay.effects.shadow),
        }
      : {}),
  };

  return (
    <div
      data-overlay-id={overlay.id}
      style={{ ...containerStyle, opacity: overlay.effects.opacity }}
      className={cn(
        "absolute select-none cursor-grab",
        isSelected && "ring-2 ring-indigo-400",
      )}
      onPointerDown={onPointerDown}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
    >
      <div style={boxStyle} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Style helpers
// ---------------------------------------------------------------------------

function positionContainerStyle(
  transform: TransformProps,
  layerIndex: number,
): CSSProperties {
  return {
    left: `${transform.x * 100}%`,
    top: `${transform.y * 100}%`,
    transform: `translate(-50%, -50%) rotate(${transform.rotationDeg}deg)`,
    pointerEvents: "auto",
    zIndex: layerIndex,
  };
}

function textShadowAndStrokeStyles(e: EffectsProps): CSSProperties {
  const out: CSSProperties = {};
  if (e.stroke) {
    // -webkit-text-stroke is supported across modern browsers; falls back
    // gracefully to no stroke on older targets.
    (out as CSSProperties & { WebkitTextStroke?: string }).WebkitTextStroke =
      `${e.stroke.widthPx}px ${e.stroke.color}`;
  }
  if (e.shadow) {
    out.textShadow = cssTextShadow(e.shadow);
  }
  return out;
}

function cssTextShadow(s: ShadowProps): string {
  // CSS text-shadow has no spread; we approximate by stacking offsets in a
  // small ring so a wider/spread shadow still reads. Blur is native.
  if (s.spreadPx > 0) {
    const offsets: Array<[number, number]> = [];
    const r = Math.max(1, s.spreadPx);
    for (let dx = -r; dx <= r; dx += Math.max(1, Math.floor(r / 2))) {
      for (let dy = -r; dy <= r; dy += Math.max(1, Math.floor(r / 2))) {
        offsets.push([s.offsetX + dx, s.offsetY + dy]);
      }
    }
    return offsets
      .map(([x, y]) => `${x}px ${y}px ${s.blurPx}px ${s.color}`)
      .join(", ");
  }
  return `${s.offsetX}px ${s.offsetY}px ${s.blurPx}px ${s.color}`;
}

function cssBoxShadow(s: ShadowProps): string {
  // box-shadow supports spread natively.
  return `${s.offsetX}px ${s.offsetY}px ${s.blurPx}px ${s.spreadPx}px ${s.color}`;
}
