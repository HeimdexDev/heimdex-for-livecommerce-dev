"use client";

// figma: 1713:275432  (cache: .figma-cache/1713-275432_phase5_editor-3.api.json)
// node-name: 프리셋 섹션 (현재 스타일 저장 + 프리셋 리스트 apply/share/delete)
// spec: 저장 버튼 w=full h=auto r=8 padLR=12 padTB=8, 리스트 row r=8 padLR=10 padTB=6 gap=2

import { useState } from "react";

import { cn } from "@/lib/utils";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlay, PresetKind, WirePreset } from "../../lib/overlay-types";
import type { PresetsApi } from "../../hooks/usePresets";
import { TemplateSaveDialog } from "../TemplateSaveDialog";

interface PresetSectionProps {
  overlay: EditorOverlay;
  presetsApi: PresetsApi;
  onApply: (preset: WirePreset) => void;
}

/**
 * Named preset save + apply + delete for the selected overlay.
 *
 * Save flow goes through `TemplateSaveDialog` so the name + share-toggle
 * inputs live in a modal (matches Figma "현재 스타일을 템플릿으로 저장"
 * state). Apply / delete / org-share-toggle remain inline per row; only
 * the owner sees the share toggle + delete button.
 */
export function PresetSection({
  overlay,
  presetsApi,
  onApply,
}: PresetSectionProps) {
  const { presets, isLoading, error, save, remove, setShared } = presetsApi;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  // Filter to overlays of the same kind — applying a text preset to a
  // background overlay would cross-pollinate fields and break round-trip.
  const visiblePresets = presets.filter(
    (p) => p.kind === (overlay.kind as PresetKind),
  );

  const handleSave = async (name: string, isShared: boolean) => {
    const created = await save(name, overlay, isShared);
    if (created) {
      setSelectedId(created.id);
      setDialogOpen(false);
    }
  };

  const handleApply = (preset: WirePreset) => {
    setSelectedId(preset.id);
    onApply(preset);
  };

  return (
    <section className="space-y-2">
      <header className="text-xs font-semibold text-grayscale-800">
        {t.preset.sectionLabel}
      </header>

      <button
        type="button"
        onClick={() => setDialogOpen(true)}
        className="w-full rounded-lg border border-grayscale-200 bg-white px-3 py-2 text-xs font-medium text-grayscale-800 transition-colors hover:border-heimdex-navy-500 hover:text-heimdex-navy-500"
      >
        {t.preset.saveButton}
      </button>

      {/* Preset list — only owner gets share + delete buttons */}
      {isLoading ? (
        <p className="text-xs text-grayscale-400">{t.preset.loadingState}</p>
      ) : visiblePresets.length === 0 ? (
        <p className="text-xs text-grayscale-400">{t.preset.emptyState}</p>
      ) : (
        <ul className="space-y-1">
          {visiblePresets.map((preset) => {
            const isActive = preset.id === selectedId;
            return (
              <li
                key={preset.id}
                className={cn(
                  "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-colors",
                  isActive
                    ? "border-heimdex-navy-400 bg-grayscale-10"
                    : "border-grayscale-100 hover:bg-grayscale-10",
                )}
              >
                <span className="flex-1 truncate text-xs text-grayscale-800">
                  {preset.name}
                </span>

                {preset.is_shared && (
                  <span className="rounded bg-grayscale-100 px-1 text-[10px] font-medium text-grayscale-800">
                    {t.preset.sharedBadge}
                  </span>
                )}

                <button
                  type="button"
                  onClick={() => handleApply(preset)}
                  className="text-[12px] font-semibold text-heimdex-navy-500 transition-colors hover:text-heimdex-navy-600"
                >
                  {t.preset.applyButton}
                </button>

                {preset.is_owned && (
                  <>
                    <button
                      type="button"
                      onClick={() => void setShared(preset.id, !preset.is_shared)}
                      className="text-[10px] text-grayscale-400 transition-colors hover:text-heimdex-navy-500"
                      aria-label={t.preset.shareToggleLabel}
                    >
                      {preset.is_shared ? "조직 ●" : "조직 ○"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void remove(preset.id)}
                      className="text-[10px] text-grayscale-400 transition-colors hover:text-red-h-500"
                      aria-label={t.preset.deletePresetTooltip}
                    >
                      삭제
                    </button>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {error && <p className="text-[11px] text-red-h-500">{error}</p>}

      <TemplateSaveDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
      />
    </section>
  );
}
