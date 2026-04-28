"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { t } from "../../lib/i18n/strings";
import type { EditorOverlay, PresetKind, WirePreset } from "../../lib/overlay-types";
import type { PresetsApi } from "../../hooks/usePresets";

interface PresetSectionProps {
  overlay: EditorOverlay;
  presetsApi: PresetsApi;
  onApply: (preset: WirePreset) => void;
}

/**
 * Named preset save + apply + delete for the selected overlay.
 *
 * Save button captures the overlay's current style as a preset; the dropdown
 * lets the user re-apply any preset to the currently selected overlay,
 * preserving its identity (id, kind, timing, position, layer index).
 *
 * Org-shared presets are visible to everyone in the org but only the owner
 * sees the share toggle + delete button.
 */
export function PresetSection({
  overlay,
  presetsApi,
  onApply,
}: PresetSectionProps) {
  const { presets, isLoading, error, save, remove, setShared } = presetsApi;
  const [name, setName] = useState("");
  const [pendingShared, setPendingShared] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Filter to overlays of the same kind — applying a text preset to a
  // background overlay would cross-pollinate fields and break round-trip.
  const visiblePresets = presets.filter(
    (p) => p.kind === (overlay.kind as PresetKind),
  );

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const created = await save(trimmed, overlay, pendingShared);
    if (created) {
      setName("");
      setPendingShared(false);
      setSelectedId(created.id);
    }
  };

  const handleApply = (preset: WirePreset) => {
    setSelectedId(preset.id);
    onApply(preset);
  };

  return (
    <section className="space-y-2">
      <header className="text-xs font-semibold text-gray-700">
        {t.preset.sectionLabel}
      </header>

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleSave();
          }}
          placeholder={t.preset.namePlaceholder}
          className="flex-1 border-b border-gray-300 bg-transparent px-1 py-1 text-xs text-gray-900 placeholder-gray-400 focus:border-indigo-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={handleSave}
          disabled={!name.trim()}
          className={cn(
            "rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
            name.trim()
              ? "border-gray-300 text-gray-700 hover:bg-gray-50"
              : "border-gray-200 text-gray-400 cursor-not-allowed",
          )}
        >
          {t.preset.saveButton}
        </button>
      </div>

      <label className="flex items-center gap-2 text-xs text-gray-500">
        <input
          type="checkbox"
          checked={pendingShared}
          onChange={(e) => setPendingShared(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
        />
        {t.preset.shareToggleLabel}
      </label>

      {/* Preset list — clicking applies; only owner gets delete + share */}
      {isLoading ? (
        <p className="text-xs text-gray-400">{t.preset.loadingState}</p>
      ) : visiblePresets.length === 0 ? (
        <p className="text-xs text-gray-400">{t.preset.emptyState}</p>
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
                    ? "border-indigo-300 bg-indigo-50/50"
                    : "border-gray-100 hover:bg-gray-50",
                )}
              >
                <button
                  type="button"
                  onClick={() => handleApply(preset)}
                  className="flex-1 truncate text-left text-xs text-gray-700"
                >
                  {preset.name}
                </button>

                {preset.is_shared && (
                  <span className="rounded bg-indigo-100 px-1 text-[10px] font-medium text-indigo-700">
                    {t.preset.sharedBadge}
                  </span>
                )}

                {preset.is_owned && (
                  <>
                    <button
                      type="button"
                      onClick={() => void setShared(preset.id, !preset.is_shared)}
                      className="text-[10px] text-gray-400 hover:text-indigo-600"
                      aria-label={t.preset.shareToggleLabel}
                    >
                      {preset.is_shared ? "조직 ●" : "조직 ○"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void remove(preset.id)}
                      className="text-[10px] text-gray-400 hover:text-red-500"
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

      {error && <p className="text-[11px] text-red-500">{error}</p>}
    </section>
  );
}
