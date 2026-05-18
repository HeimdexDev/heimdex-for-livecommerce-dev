"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 배경 툴바 (line-spacing placeholder + layer order + fill color)
// spec: gap=1 (mx-1 separator), radius·padding 은 ToolbarButton/Dropdown primitive 사용

import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { Dropdown } from "../primitives/Dropdown";
import { LayerStackIcon, LineSpacingIcon } from "../primitives/icons";
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
 * Smaller toolbar for the background tab — line-spacing kept for layout
 * parity with Figma (it's effectively a no-op for backgrounds), layer
 * dropdown, fill color.
 */
export function BackgroundToolbar({
  overlay,
  onChange,
  onReorder,
}: BackgroundToolbarProps) {
  // Goal capture (background wrapper) — action bar is right-aligned: the
  // three icons (line-spacing / layer / paint bucket) cluster against the
  // wrapper's right edge with empty space to the left. Using justify-end
  // keeps the same component tree and only flips the row alignment.
  return (
    <div className="flex items-center justify-end gap-1">
      <ToolbarButton ariaLabel={t.text.lineSpacing} disabled>
        <LineSpacingIcon />
      </ToolbarButton>

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

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

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

      <ColorSwatchButton
        color={overlay.fillColor}
        onChange={(color) => onChange({ fillColor: color })}
        ariaLabel={t.background.fillColor}
        size="sm"
      />
    </div>
  );
}
