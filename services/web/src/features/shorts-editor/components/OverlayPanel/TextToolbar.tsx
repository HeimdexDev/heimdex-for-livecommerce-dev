"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 텍스트 툴바 (B/I/U + align + line-spacing + color + highlight)
// spec: gap=1 (separator=mx-1 1px), radius·padding 은 ToolbarButton/Dropdown primitive 사용

import { ColorSwatchButton } from "../primitives/ColorSwatchButton";
import { Dropdown } from "../primitives/Dropdown";
import {
  AlignCenterIcon,
  AlignLeftIcon,
  AlignRightIcon,
  BoldIcon,
  ChevronDownIcon,
  ItalicIcon,
  LineSpacingIcon,
  PaintBucketIcon,
  UnderlineIcon,
} from "../primitives/icons";
import { ToolbarButton } from "../primitives/ToolbarButton";
import { t } from "../../lib/i18n/strings";
import type { EditorTextOverlay } from "../../lib/overlay-types";

const LINE_SPACING_OPTIONS = [
  { value: 1.0, label: "1.0" },
  { value: 1.15, label: "1.15" },
  { value: 1.3, label: "1.3" },
  { value: 1.5, label: "1.5" },
  { value: 2.0, label: "2.0" },
] as const;

interface TextToolbarProps {
  overlay: EditorTextOverlay;
  onChange: (updates: Partial<EditorTextOverlay>) => void;
}

/**
 * B / I / U | text-align | line-spacing | font-color | highlight-color.
 *
 * Bold is a binary toggle on font_weight (400 / 700) — matches V1's "보통/굵게"
 * behavior so existing presets keep applying cleanly. A future change to
 * full weight selection would replace this with a numeric stepper.
 */
export function TextToolbar({ overlay, onChange }: TextToolbarProps) {
  const isBold = overlay.fontWeight >= 600;

  const alignIcon =
    overlay.textAlign === "left" ? (
      <AlignLeftIcon />
    ) : overlay.textAlign === "right" ? (
      <AlignRightIcon />
    ) : (
      <AlignCenterIcon />
    );

  return (
    <div className="flex items-center gap-1">
      <ToolbarButton
        active={isBold}
        onClick={() => onChange({ fontWeight: isBold ? 400 : 700 })}
        ariaLabel={t.text.bold}
      >
        <BoldIcon />
      </ToolbarButton>
      <ToolbarButton
        active={overlay.italic}
        onClick={() => onChange({ italic: !overlay.italic })}
        ariaLabel={t.text.italic}
      >
        <ItalicIcon />
      </ToolbarButton>
      <ToolbarButton
        active={overlay.underline}
        onClick={() => onChange({ underline: !overlay.underline })}
        ariaLabel={t.text.underline}
      >
        <UnderlineIcon />
      </ToolbarButton>

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

      {/* Alignment cycle: hidden details — clicking advances left → center → right */}
      <ToolbarButton
        ariaLabel={t.text.align}
        onClick={() => {
          const next: EditorTextOverlay["textAlign"] =
            overlay.textAlign === "left"
              ? "center"
              : overlay.textAlign === "center"
              ? "right"
              : "left";
          onChange({ textAlign: next });
        }}
      >
        {alignIcon}
      </ToolbarButton>
      <ChevronDownIcon className="h-3 w-3 text-grayscale-400" />

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

      {/* Line spacing — dropdown */}
      <ToolbarButton ariaLabel={t.text.lineSpacing}>
        <LineSpacingIcon />
      </ToolbarButton>
      <Dropdown
        value={
          (LINE_SPACING_OPTIONS.find((o) => o.value === overlay.lineHeight)
            ?.value as number) ?? overlay.lineHeight
        }
        options={LINE_SPACING_OPTIONS}
        onChange={(v) => onChange({ lineHeight: Number(v) })}
        ariaLabel={t.text.lineSpacing}
        className="!px-1.5 !py-1 !text-xs"
      />

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

      {/* Font color — A icon with a thin red-underline hint, native picker */}
      <div className="relative">
        <ColorSwatchButton
          color={overlay.fontColor}
          onChange={(color) => onChange({ fontColor: color })}
          ariaLabel={t.text.color}
          size="sm"
        />
      </div>

      {/* Highlight color (paint-bucket) — toggles a non-null highlight on first
          click, then opens picker on subsequent clicks. */}
      <ToolbarButton
        active={overlay.highlightColor != null}
        onClick={() =>
          onChange({
            highlightColor: overlay.highlightColor ? null : "#FFE600",
          })
        }
        ariaLabel={t.text.highlight}
      >
        <PaintBucketIcon />
      </ToolbarButton>
    </div>
  );
}
