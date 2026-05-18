"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 배경 툴바 (line-spacing placeholder + layer order + fill color)
// spec: gap=1 (mx-1 separator), radius·padding 은 ToolbarButton/Dropdown primitive 사용

import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { Dropdown } from "../primitives/Dropdown";
import { CanvasAlignCenterIcon, LayerStackIcon } from "../primitives/icons";
import { ToolbarButton } from "../primitives/ToolbarButton";
import { t } from "../../lib/i18n/strings";
import type { EditorBackgroundOverlay } from "../../lib/overlay-types";

const LAYER_OPTIONS = [
  { value: "front", label: t.background.bringToFront },
  { value: "forward", label: t.background.bringForward },
  { value: "backward", label: t.background.sendBackward },
  { value: "back", label: t.background.sendToBack },
] as const;

interface BackgroundToolbarProps {
  overlay: EditorBackgroundOverlay;
  onChange: (updates: Partial<EditorBackgroundOverlay>) => void;
  onReorder: (direction: "front" | "back" | "forward" | "backward") => void;
}

/**
 * Background tab toolbar — alignment toggle + layer dropdown + fill color.
 *
 * The alignment button cycles the overlay between horizontal-center
 * (x=0.5), vertical-center (y=0.5), and full-center (both axes). Each
 * press advances one step in the cycle so a single icon serves as the
 * "가로/세로 중앙정렬" affordance from the 2026-05-18 goal capture
 * without growing the toolbar.
 */
export function BackgroundToolbar({
  overlay,
  onChange,
  onReorder,
}: BackgroundToolbarProps) {
  const handleAlign = () => {
    const { x, y } = overlay.transform;
    // Three-step rotation: horizontal-center → vertical-center → both.
    // The starting state is whichever axis is not already 0.5, so the
    // first click is always meaningful regardless of where the overlay
    // currently sits.
    const isHCentered = Math.abs(x - 0.5) < 0.001;
    const isVCentered = Math.abs(y - 0.5) < 0.001;
    let nextX = x;
    let nextY = y;
    if (!isHCentered && !isVCentered) {
      nextX = 0.5;
    } else if (isHCentered && !isVCentered) {
      nextY = 0.5;
    } else if (!isHCentered && isVCentered) {
      nextX = 0.5;
    } else {
      // Both already centered — toggle back to horizontal-center only so
      // a second press has a visible effect.
      nextY = overlay.transform.y === 0.5 ? 0.85 : 0.5;
    }
    onChange({
      transform: { ...overlay.transform, x: nextX, y: nextY },
    });
  };

  return (
    <div className="flex items-center justify-end gap-1">
      <ToolbarButton
        ariaLabel="가로/세로 중앙정렬"
        onClick={handleAlign}
      >
        <CanvasAlignCenterIcon />
      </ToolbarButton>

      <span className="mx-1 h-5 w-px bg-grayscale-100" />

      <ToolbarButton ariaLabel={t.background.layerOrder}>
        <LayerStackIcon />
      </ToolbarButton>
      <Dropdown
        value="forward"
        options={LAYER_OPTIONS}
        onChange={(v) =>
          onReorder(v as "front" | "back" | "forward" | "backward")
        }
        ariaLabel={t.background.layerOrder}
        className="!px-1.5 !py-1 !text-xs"
      />

      <span className="mx-1 h-5 w-px bg-grayscale-100" />

      <ColorSwatchButton
        color={overlay.fillColor}
        onChange={(color) => onChange({ fillColor: color })}
        ariaLabel={t.background.fillColor}
        size="sm"
      />
    </div>
  );
}
