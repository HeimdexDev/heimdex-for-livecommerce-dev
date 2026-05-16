"use client";

import { cn } from "@/lib/utils";
import { ImageIcon, PlusIcon, TrashIcon } from "../primitives/icons";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlayKind } from "../../lib/overlay-types";

interface ActionBarProps {
  kind: EditorOverlayKind;
  onAdd: () => void;
  onDelete: () => void;
  canDelete: boolean;
}

/**
 * Top action row for the overlay panel.
 *
 * Text tab: [+ 텍스트 추가] [trash]
 * Background tab: [+ 단색 배경 추가] [이미지 삽입 (disabled)] [trash]
 *
 * The image-insert button is intentionally rendered but disabled — the
 * Figma asks for the layout to be present even though the feature ships
 * later. Tooltip explains.
 */
export function ActionBar({
  kind,
  onAdd,
  onDelete,
  canDelete,
}: ActionBarProps) {
  const addLabel = kind === "text" ? t.actions.addText : t.actions.addBackground;

  return (
    <div className="flex items-stretch gap-2">
      <button
        type="button"
        onClick={onAdd}
        className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-heimdex-navy-500 px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-heimdex-navy-600"
      >
        <PlusIcon />
        {addLabel}
      </button>

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

      <button
        type="button"
        onClick={onDelete}
        disabled={!canDelete}
        aria-label={t.actions.deleteSelected}
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-lg border transition-colors",
          canDelete
            ? "border-red-300 text-red-500 hover:bg-red-50"
            : "border-grayscale-200 text-grayscale-300 cursor-not-allowed",
        )}
      >
        <TrashIcon />
      </button>
    </div>
  );
}
