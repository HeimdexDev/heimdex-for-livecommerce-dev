"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 텍스트 툴바 (B/I/U + align + line-spacing + color + highlight)
// spec: gap=1 (separator=mx-1 1px), radius·padding 은 ToolbarButton/Dropdown primitive 사용

import { useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { ColorPalettePopover } from "../primitives/ColorPalettePopover";
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

const DEFAULT_HIGHLIGHT = "#FFE600";

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

      {/* figma 1602:40064 — 폰트 색상: "A" 글자 + 하단 색상 바.
          클릭 시 ColorPalettePopover 가 열린다. */}
      <ColorTriggerButton
        ariaLabel={t.text.color}
        color={overlay.fontColor}
        onChange={(color) => onChange({ fontColor: color })}
      >
        <span className="text-[18px] font-medium leading-[1.4] tracking-[-0.45px] text-grayscale-800">
          A
        </span>
      </ColorTriggerButton>

      {/* figma 1602:40066 — 하이라이트 색상: PaintBucket + 하단 색상 바.
          클릭 시 팔레트 팝업이 열리고, 색상을 고르면 highlightColor 가
          지정된다. 팔레트 안 "기본 색상" 영역에서 흰색·투명 계열을 골라
          하이라이트를 끄는 식으로 비활성화한다. */}
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
