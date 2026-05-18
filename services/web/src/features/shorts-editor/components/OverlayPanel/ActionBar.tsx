"use client";

import { useRef, useState } from "react";

import { ColorPalettePopover } from "../primitives/ColorPalettePopover";
import { ColorPalettePortal } from "../primitives/ColorPalettePortal";
import { ImageIcon, PlusIcon } from "../primitives/icons";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlayKind } from "../../lib/overlay-types";

interface ActionBarProps {
  kind: EditorOverlayKind;
  onAddText: () => void;
  // figma 1602:40004 배경 섹션 — 단색 배경 추가 버튼은 색상 팔레트
  // 팝업을 열고, 선택한 색상을 fillColor 로 함께 전달한다.
  onAddBackground: (fillColor: string) => void;
  // "Insert image" — receives the data URL of the picked file. When
  // omitted (e.g., text tab) the image button is hidden.
  onAddImage?: (dataUrl: string) => void;
}

const DEFAULT_BG_FILL = "#000000";
// File picker accepts MIME types; spelled out so unsupported types
// (.heic, .tiff) don't slip through and surprise the renderer.
const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif,image/svg+xml";

/**
 * Top action row for the overlay panel.
 *
 * Text tab: [+ 텍스트 추가]
 * Background tab: [+ 단색 배경 추가] [이미지 삽입]
 *
 * "+ 단색 배경 추가" opens the ColorPalettePopover (figma 1602:41332)
 * anchored under the button — the picked color is used as the new
 * overlay's fillColor.
 *
 * "이미지 삽입" surfaces a hidden ``<input type="file">`` whose change
 * handler reads the picked file as a data URL and forwards it via
 * onAddImage. The image lands as a new background overlay with the
 * image painted on top of a transparent fill, with full transform /
 * effects controls available in the rest of the panel.
 */
export function ActionBar({
  kind,
  onAddText,
  onAddBackground,
  onAddImage,
}: ActionBarProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingFill, setPendingFill] = useState(DEFAULT_BG_FILL);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const handleAddClick = () => {
    if (kind === "text") {
      onAddText();
    } else {
      setPickerOpen((v) => !v);
    }
  };

  const handleImageClick = () => {
    imageInputRef.current?.click();
  };

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // Reset the input so picking the same file twice still fires a
    // change event; otherwise the second pick is silently dropped.
    e.target.value = "";
    if (!file || !onAddImage) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") onAddImage(reader.result);
    };
    reader.readAsDataURL(file);
  };

  return (
    <div className="flex items-stretch gap-2">
      <div className="relative flex flex-1">
        <button
          ref={triggerRef}
          type="button"
          onClick={handleAddClick}
          aria-haspopup={kind === "background" ? "dialog" : undefined}
          aria-expanded={kind === "background" ? pickerOpen : undefined}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-heimdex-navy-500 px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
        >
          <PlusIcon />
          {kind === "text" ? t.actions.addText : t.actions.addBackground}
        </button>
        {kind === "background" && pickerOpen && (
          <ColorPalettePortal anchorRef={triggerRef} onClose={() => setPickerOpen(false)}>
            <ColorPalettePopover
              color={pendingFill}
              onChange={(next) => {
                const fill = next.toUpperCase();
                setPendingFill(fill);
                onAddBackground(fill);
                setPickerOpen(false);
              }}
              onClose={() => setPickerOpen(false)}
              showOpacity={false}
            />
          </ColorPalettePortal>
        )}
      </div>

      {kind === "background" && (
        <>
          <button
            type="button"
            onClick={handleImageClick}
            aria-label={t.actions.insertImage}
            className="flex items-center justify-center gap-1.5 rounded-lg border border-grayscale-200 px-3 py-2.5 text-sm font-medium text-grayscale-800 transition-colors hover:bg-grayscale-50"
          >
            <ImageIcon />
            {t.actions.insertImage}
          </button>
          <input
            ref={imageInputRef}
            type="file"
            accept={IMAGE_ACCEPT}
            onChange={handleImageChange}
            className="sr-only"
            aria-hidden
            tabIndex={-1}
          />
        </>
      )}
    </div>
  );
}
