"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 텍스트 툴바 (B/I/U + align + line-spacing + color + highlight)
// spec: gap=1 (separator=mx-1 1px), radius·padding 은 ToolbarButton/Dropdown primitive 사용

import { useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { ColorPalettePopover } from "../primitives/ColorPalettePopover";
import {
  AlignCenterIcon,
  AlignLeftIcon,
  AlignRightIcon,
  BoldIcon,
  CanvasAlignCenterIcon,
  ChevronDownIcon,
  ItalicIcon,
  PaintBucketIcon,
  UnderlineIcon,
} from "../primitives/icons";
import { ToolbarButton } from "../primitives/ToolbarButton";
import { t } from "../../lib/i18n/strings";
import type { EditorTextOverlay } from "../../lib/overlay-types";

const DEFAULT_HIGHLIGHT = "#FFE600";

interface TextToolbarProps {
  overlay: EditorTextOverlay;
  onChange: (updates: Partial<EditorTextOverlay>) => void;
}

/**
 * B / I / U | text-align cycle | canvas-align cycle | font color | highlight.
 *
 * Bold is a binary toggle on font_weight (400 / 700) — matches V1's "보통/굵게"
 * behavior so existing presets keep applying cleanly. The line-spacing
 * dropdown was removed per 2026-05-18 figma redesign; lineHeight stays in
 * the data model with its default and can still be set via presets.
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

  // Canvas alignment trigger — applies center on the active axis. The
  // chevron flips the local axis state without touching transform.x/y so
  // the user can pick which axis to center next. Mirrors the text-align
  // cycle pattern (icon + chevron) the user explicitly referenced.
  const [canvasAxis, setCanvasAxis] = useState<"vertical" | "horizontal">("vertical");

  const handleCanvasAlign = () => {
    if (canvasAxis === "vertical") {
      onChange({ transform: { ...overlay.transform, y: 0.5 } });
    } else {
      onChange({ transform: { ...overlay.transform, x: 0.5 } });
    }
  };

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
      <button
        type="button"
        onClick={() => {
          const next: EditorTextOverlay["textAlign"] =
            overlay.textAlign === "left"
              ? "center"
              : overlay.textAlign === "center"
              ? "right"
              : "left";
          onChange({ textAlign: next });
        }}
        aria-label={`${t.text.align} expand`}
        className="text-grayscale-400 hover:text-grayscale-800"
      >
        <ChevronDownIcon className="h-3 w-3" />
      </button>

      {/* Canvas-level alignment: center the overlay on the preview canvas.
          Vertical mode → transform.y = 0.5, horizontal mode → transform.x.
          The chevron flips which axis the icon represents. */}
      <ToolbarButton
        ariaLabel={canvasAxis === "vertical" ? "캔버스 세로 중앙 정렬" : "캔버스 가로 중앙 정렬"}
        onClick={handleCanvasAlign}
      >
        <CanvasAlignCenterIcon rotated={canvasAxis === "horizontal"} />
      </ToolbarButton>
      <button
        type="button"
        onClick={() =>
          setCanvasAxis((axis) => (axis === "vertical" ? "horizontal" : "vertical"))
        }
        aria-label="캔버스 정렬 축 전환"
        className="text-grayscale-400 hover:text-grayscale-800"
      >
        <ChevronDownIcon className="h-3 w-3" />
      </button>

      <span className="mx-1 h-5 w-px bg-grayscale-200" />

      {/* figma 1602:40064 — font color trigger: "A" glyph above a thin
          color bar that previews the current value. Click opens the
          shared ColorPalettePopover. */}
      <ColorTriggerButton
        ariaLabel={t.text.color}
        color={overlay.fontColor}
        onChange={(color) => onChange({ fontColor: color })}
      >
        <span className="text-[18px] font-medium leading-[1.4] tracking-[-0.45px] text-grayscale-800">
          A
        </span>
      </ColorTriggerButton>

      {/* figma 1602:40066 — highlight color trigger: paint-bucket icon
          above its color bar. Picking white/transparent from the palette
          effectively disables the highlight. */}
      <ColorTriggerButton
        ariaLabel={t.text.highlight}
        color={overlay.highlightColor ?? DEFAULT_HIGHLIGHT}
        muted={overlay.highlightColor == null}
        onChange={(color) => onChange({ highlightColor: color })}
      >
        <PaintBucketIcon />
      </ColorTriggerButton>
    </div>
  );
}

// figma 1602:40063~1602:40070 — 텍스트 색상/하이라이트 트리거.
// 28×26 공간에 아이콘이 자리잡고 그 아래 4px 색상 바가 현재 값을 미리
// 보여준다. 클릭 시 ColorPalettePopover 가 자식 트리거 바로 아래에 뜬다.
function ColorTriggerButton({
  ariaLabel,
  color,
  onChange,
  children,
  muted = false,
}: {
  ariaLabel: string;
  color: string;
  onChange: (color: string) => void;
  children: React.ReactNode;
  muted?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  return (
    <div className="relative" ref={wrapRef}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
        className="flex h-7 w-7 flex-col items-center justify-center gap-[2px] rounded"
      >
        <span
          className={cn(
            "flex h-5 w-5 items-center justify-center",
            muted && "opacity-60",
          )}
        >
          {children}
        </span>
        <span
          aria-hidden
          className="block h-[3px] w-[20px] rounded-[1px]"
          style={{ backgroundColor: muted ? "transparent" : color }}
        />
      </button>
      {open && (
        // right-0 으로 펼침 — 텍스트 툴바 의 색상 트리거가 우측 wrapper 우측 절반에
        // 위치하므로 좌측 anchor 이면 팔레트 (260px) 가 wrapper 를 넘쳐 가로 스크롤이
        // 발생한다. wrapper 안쪽으로 펼치도록 right-0 으로 통일.
        <div className="absolute right-0 top-full z-50 mt-2">
          <ColorPalettePopover
            color={color}
            onChange={(next) => {
              onChange(next.toUpperCase());
              setOpen(false);
            }}
            onClose={() => setOpen(false)}
            showOpacity={false}
          />
        </div>
      )}
    </div>
  );
}
