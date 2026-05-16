"use client";

import { type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";

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

type Corner = "nw" | "ne" | "sw" | "se";

interface OverlayRendererProps {
  overlay: EditorOverlay;
  isSelected: boolean;
  // Body drag — caller wires this to a "move" gesture that updates
  // overlay.transform.x / .y.
  onMovePointerDown?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  // Corner drag — caller wires this to a "resize" gesture that updates
  // fontSizePx (text) or transform.widthPx/heightPx (background).
  onResizePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  // Drag continuation — these MUST be attached to the same elements that
  // call setPointerCapture in the pointerdown handlers, otherwise the
  // captured element delivers events to nowhere and the gesture appears
  // frozen. (Symptom in V2 v1: handles render but dragging does nothing.)
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onClick?: () => void;
}

/**
 * Renders an EditorOverlay (text or background) as a positioned, styled
 * <div>/<p> in the preview canvas. Pure: no state, no network — caller
 * controls selection + drag math.
 *
 * Drag UX (matches V1 PreviewPanel's subtitle behavior):
 * - Body pointerdown → caller-driven "move" — translates X/Y delta into
 *   normalized transform.x/y updates.
 * - Corner pointerdown (when selected) → caller-driven "resize" —
 *   translates radial distance ratio into a proportional fontSizePx
 *   (text) or widthPx/heightPx (background) update.
 *
 * Visual fidelity:
 * - Browser kerning vs PIL kerning will drift slightly (Risk 3 in plan).
 * - Stroke is rendered via -webkit-text-stroke (text) or outline (bg).
 * - Shadow uses CSS text-shadow stack / box-shadow (with spread).
 */
export function OverlayRenderer({
  overlay,
  isSelected,
  onMovePointerDown,
  onResizePointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
}: OverlayRendererProps) {
  const sharedProps = {
    isSelected,
    onMovePointerDown,
    onResizePointerDown,
    onPointerMove,
    onPointerUp,
    onClick,
  };
  if (overlay.kind === "text") {
    return <TextOverlayBox overlay={overlay} {...sharedProps} />;
  }
  return <BackgroundOverlayBox overlay={overlay} {...sharedProps} />;
}

// ---------------------------------------------------------------------------
// Text overlay
// ---------------------------------------------------------------------------

function TextOverlayBox({
  overlay,
  isSelected,
  onMovePointerDown,
  onResizePointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
}: {
  overlay: EditorTextOverlay;
  isSelected: boolean;
  onMovePointerDown?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onResizePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onClick?: () => void;
}) {
  const containerStyle = positionContainerStyle(overlay.transform, overlay.layerIndex);

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
        "absolute select-none cursor-grab active:cursor-grabbing",
        isSelected && "ring-2 ring-indigo-400 ring-offset-1",
      )}
      onPointerDown={onMovePointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
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

      {isSelected && onResizePointerDown && (
        <ResizeHandles
          onResize={onResizePointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
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
  onMovePointerDown,
  onResizePointerDown,
  onPointerMove,
  onPointerUp,
  onClick,
}: {
  overlay: EditorBackgroundOverlay;
  isSelected: boolean;
  onMovePointerDown?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onResizePointerDown?: (
    corner: Corner,
    e: ReactPointerEvent<HTMLDivElement>,
  ) => void;
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
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
        "absolute select-none cursor-grab active:cursor-grabbing",
        isSelected && "ring-2 ring-indigo-400 ring-offset-1",
      )}
      onPointerDown={onMovePointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
    >
      <div style={boxStyle} />

      {isSelected && onResizePointerDown && (
        <ResizeHandles
          onResize={onResizePointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Resize handles (4 corners)
// ---------------------------------------------------------------------------

const CORNER_STYLES: Record<Corner, string> = {
  nw: "-top-1.5 -left-1.5 cursor-nwse-resize",
  ne: "-top-1.5 -right-1.5 cursor-nesw-resize",
  sw: "-bottom-1.5 -left-1.5 cursor-nesw-resize",
  se: "-bottom-1.5 -right-1.5 cursor-nwse-resize",
};

function ResizeHandles({
  onResize,
  onPointerMove,
  onPointerUp,
}: {
  onResize: (corner: Corner, e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerMove?: (e: ReactPointerEvent<HTMLDivElement>) => void;
  onPointerUp?: (e: ReactPointerEvent<HTMLDivElement>) => void;
}) {
  return (
    <>
      {(["nw", "ne", "sw", "se"] as const).map((corner) => (
        <div
          key={corner}
          className={cn(
            "absolute z-10 h-3 w-3 rounded-full border-2 border-white bg-indigo-500",
            CORNER_STYLES[corner],
          )}
          onPointerDown={(e) => onResize(corner, e)}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          // Stop click bubbling so corner clicks don't double as
          // body-clicks (which would re-fire selection).
          onClick={(e) => e.stopPropagation()}
        />
      ))}
    </>
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
    (out as CSSProperties & { WebkitTextStroke?: string }).WebkitTextStroke =
      `${e.stroke.widthPx}px ${e.stroke.color}`;
  }
  if (e.shadow) {
    out.textShadow = cssTextShadow(e.shadow);
  }
  return out;
}

function cssTextShadow(s: ShadowProps): string {
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
  return `${s.offsetX}px ${s.offsetY}px ${s.blurPx}px ${s.spreadPx}px ${s.color}`;
}
