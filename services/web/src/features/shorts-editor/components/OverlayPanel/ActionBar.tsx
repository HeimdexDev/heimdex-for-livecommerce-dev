"use client";

import { useState } from "react";

import { ColorPalettePopover } from "../primitives/ColorPalettePopover";
import { ImageIcon, PlusIcon } from "../primitives/icons";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlayKind } from "../../lib/overlay-types";

interface ActionBarProps {
  kind: EditorOverlayKind;
  onAddText: () => void;
  // figma 1602:40004 배경 섹션 — 단색 배경 추가 버튼은 색상 팔레트
  // 팝업을 열고, 선택한 색상을 fillColor 로 함께 전달한다.
  onAddBackground: (fillColor: string) => void;
}

const DEFAULT_BG_FILL = "#000000";

/**
 * Top action row for the overlay panel.
 *
 * Text tab: [+ 텍스트 추가]
 * Background tab: [+ 단색 배경 추가] [이미지 삽입 (disabled)]
 *
 * Background "+ 단색 배경 추가" opens the ColorPalettePopover (figma
 * 1602:41332) anchored under the button — the picked color is used as
 * the new overlay's fillColor. Image-insert stays disabled until ship.
 * Delete is intentionally absent — it lives on the dot-3 menu of the
 * selected overlay in the preview / layer list, not in the action bar.
 */
export function ActionBar({
  kind,
  onAddText,
  onAddBackground,
}: ActionBarProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pendingFill, setPendingFill] = useState(DEFAULT_BG_FILL);

  const handleAddClick = () => {
    if (kind === "text") {
      onAddText();
    } else {
      setPickerOpen((v) => !v);
    }
  };

  return (
    <div className="flex items-stretch gap-2">
      <div className="relative flex flex-1">
        <button
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
          <div className="absolute left-0 top-full z-50 mt-2">
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
          </div>
        )}
      </div>

      {kind === "background" && (
        <button
          type="button"
          disabled
          title={t.actions.insertImageDisabledTooltip}
          aria-label={t.actions.insertImage}
          className="flex items-center justify-center gap-1.5 rounded-lg border border-grayscale-200 px-3 py-2.5 text-sm font-medium text-grayscale-400 cursor-not-allowed"
        >
          <ImageIcon />
          {t.actions.insertImage}
        </button>
      )}
      {/* Delete button intentionally removed — the dot-3 menu inside
          OverlayLayerSelector + DEL key on the preview own the delete
          action, so the action bar stays focused on add operations. */}
    </div>
  );
}
