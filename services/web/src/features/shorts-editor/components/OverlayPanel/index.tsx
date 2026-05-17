"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Dropdown } from "../primitives/Dropdown";
import { ActionBar } from "./ActionBar";
import { BackgroundToolbar } from "./BackgroundToolbar";
import { EffectsSection, StrokeBlock } from "./EffectsSection";
import { PresetSection } from "./PresetSection";
import { TextToolbar } from "./TextToolbar";
import { TransformSection } from "./TransformSection";
import { useOverlaySelection } from "../../hooks/useOverlaySelection";
import { usePresets } from "../../hooks/usePresets";
import { t } from "../../lib/i18n/strings";
import { runOneTimePresetMigration } from "../../lib/preset-migration";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
  EditorOverlayKind,
  EditorTextOverlay,
  EffectsProps,
  TransformProps,
  WirePreset,
} from "../../lib/overlay-types";
import type { EditorState } from "../../lib/types";

const FONT_OPTIONS = [
  { value: "Pretendard", label: "Pretendard" },
  { value: "Noto Sans KR", label: "Noto Sans KR" },
] as const;

interface OverlayPanelProps {
  state: EditorState;
  onAddTextOverlay: () => void;
  onAddBackgroundOverlay: () => void;
  onUpdateOverlay: (id: string, updates: Partial<EditorOverlay>) => void;
  onRemoveOverlay: (id: string) => void;
  onSelectOverlay: (id: string | null) => void;
  onReorderOverlay: (
    id: string,
    direction: "front" | "back" | "forward" | "backward",
  ) => void;
}

/**
 * V2 overlay panel — replaces TextOverlayPanel when the feature flag is on.
 *
 * Tab state is local to the panel: tabs reflect what the user wants to be
 * editing, NOT the kind of the selected overlay. If the user has a text
 * overlay selected and switches to the Background tab, the panel switches
 * to a "you have no background selected" empty state and shows the bg
 * actions; the text overlay remains in state.
 *
 * When the user clicks "+ 텍스트 추가" or "+ 단색 배경 추가" we add an overlay
 * of the matching kind, which the reducer auto-selects, and the panel
 * fills with its fields.
 */
export function OverlayPanel({
  state,
  onAddTextOverlay,
  onAddBackgroundOverlay,
  onUpdateOverlay,
  onRemoveOverlay,
  onSelectOverlay,
  onReorderOverlay,
}: OverlayPanelProps) {
  const { selected } = useOverlaySelection(state);
  const [tab, setTab] = useState<EditorOverlayKind>("text");
  const { getAccessToken } = useAuth();

  // Auto-switch tab when the selected overlay's kind doesn't match — the
  // user clicked an overlay in the preview, the panel should follow.
  useEffect(() => {
    if (selected && selected.kind !== tab) {
      setTab(selected.kind);
    }
  }, [selected, tab]);

  // Selected overlay only counts when its kind matches the current tab —
  // otherwise the empty state for the current tab takes over.
  const selectedForTab =
    selected && selected.kind === tab ? selected : null;

  const presetsApi = usePresets({
    kind: tab,
    getToken: getAccessToken,
    enabled: true,
  });

  // One-time legacy localStorage → API migration. Idempotent: the migration
  // module itself short-circuits on a "migrated" flag in localStorage, so
  // running this on every mount is cheap (one localStorage read) for users
  // who never had V1 presets or have already migrated.
  useEffect(() => {
    let cancelled = false;
    void runOneTimePresetMigration(getAccessToken).then((result) => {
      if (!cancelled && result.migrated > 0) {
        // Refresh so newly imported presets show up in the dropdown.
        void presetsApi.reload();
      }
    });
    return () => {
      cancelled = true;
    };
    // presetsApi.reload changes reference each render — intentionally not in
    // deps; we only want this to fire once per panel mount, not on every
    // re-render. getAccessToken is stable (auth hook).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getAccessToken]);

  return (
    <div className="flex h-full flex-col">
      {/* RightPanel hosts the outer 텍스트/배경/템플릿 tab strip, so the
          panel-internal tab bar is intentionally omitted here to avoid
          rendering a duplicate row inside the same surface. */}
      <div className="flex-1 space-y-4 overflow-y-auto">
        <ActionBar
          kind={tab}
          onAdd={tab === "text" ? onAddTextOverlay : onAddBackgroundOverlay}
          onDelete={() => {
            if (selectedForTab) onRemoveOverlay(selectedForTab.id);
          }}
          canDelete={selectedForTab != null}
        />

        {selectedForTab == null ? (
          <p className="rounded-lg bg-grayscale-10 px-3 py-8 text-center text-xs text-grayscale-400">
            {t.empty.panelHint}
          </p>
        ) : selectedForTab.kind === "text" ? (
          <TextEditingBody
            overlay={selectedForTab as EditorTextOverlay}
            onUpdate={(updates) =>
              onUpdateOverlay(selectedForTab.id, updates)
            }
          />
        ) : (
          <BackgroundEditingBody
            overlay={selectedForTab as EditorBackgroundOverlay}
            onUpdate={(updates) =>
              onUpdateOverlay(selectedForTab.id, updates)
            }
            onReorder={(direction) =>
              onReorderOverlay(selectedForTab.id, direction)
            }
          />
        )}

        {selectedForTab && (
          <PresetSection
            overlay={selectedForTab}
            presetsApi={presetsApi}
            onApply={(preset: WirePreset) => {
              const merged = presetsApi.applyTo(selectedForTab, preset);
              onUpdateOverlay(selectedForTab.id, merged);
            }}
          />
        )}
      </div>

      {/* Selection drag tracker so the user can click a different overlay
          via the layer order without switching tabs. Hidden until > 1 overlay. */}
      {state.overlays.length > 1 && (
        <OverlaySelectorRow
          state={state}
          onSelect={onSelectOverlay}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Text editing body
// ---------------------------------------------------------------------------

function TextEditingBody({
  overlay,
  onUpdate,
}: {
  overlay: EditorTextOverlay;
  onUpdate: (updates: Partial<EditorTextOverlay>) => void;
}) {
  return (
    <div className="space-y-4">
      <textarea
        value={overlay.text}
        onChange={(e) => onUpdate({ text: e.target.value.slice(0, 500) })}
        placeholder={t.text.contentPlaceholder}
        rows={4}
        maxLength={500}
        // figma 1663:45770 — Text Area Section: h-114 2px heimdex-navy/500
        // border, 10px radius, px-14 py-16.
        className="h-[114px] w-full resize-none rounded-[10px] border-2 border-heimdex-navy-500 bg-white px-[14px] py-[16px] text-[14px] tracking-[-0.35px] text-neutral-h-800 placeholder-neutral-h-300 focus:outline-none"
      />

      <div className="grid grid-cols-[1fr_120px] gap-2">
        <Dropdown
          value={overlay.fontFamily}
          options={FONT_OPTIONS}
          onChange={(v) =>
            onUpdate({ fontFamily: v as EditorTextOverlay["fontFamily"] })
          }
          ariaLabel={t.text.fontFamily}
        />
        <NumericFieldWithUnit
          value={overlay.fontSizePx}
          unit="pt"
          min={8}
          max={200}
          onChange={(v) => onUpdate({ fontSizePx: v })}
        />
      </div>

      <TextToolbar overlay={overlay} onChange={onUpdate} />

      <hr className="border-grayscale-100" />

      {/* figma 1663:45821 — 변형 + 윤곽선 nudged into a 2-col row */}
      <div className="grid grid-cols-2 gap-3">
        <TransformSection
          overlay={overlay}
          onChange={(transform: TransformProps) => onUpdate({ transform })}
        />
        <StrokeBlock
          effects={overlay.effects}
          onChange={(effects: EffectsProps) => onUpdate({ effects })}
        />
      </div>

      <hr className="border-grayscale-100" />

      <EffectsSection
        effects={overlay.effects}
        onChange={(effects: EffectsProps) => onUpdate({ effects })}
        hideStroke
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background editing body
// ---------------------------------------------------------------------------

function BackgroundEditingBody({
  overlay,
  onUpdate,
  onReorder,
}: {
  overlay: EditorBackgroundOverlay;
  onUpdate: (updates: Partial<EditorBackgroundOverlay>) => void;
  onReorder: (direction: "front" | "back" | "forward" | "backward") => void;
}) {
  return (
    <div className="space-y-4">
      <BackgroundToolbar
        overlay={overlay}
        onChange={onUpdate}
        onReorder={onReorder}
      />

      <hr className="border-grayscale-100" />

      {/* figma 1607:65622 — 변형 + 윤곽선 in one row, size/rotation lives only on Transform side */}
      <div className="grid grid-cols-2 gap-3">
        <TransformSection
          overlay={overlay}
          onChange={(transform: TransformProps) => onUpdate({ transform })}
        />
        <StrokeBlock
          effects={overlay.effects}
          onChange={(effects: EffectsProps) => onUpdate({ effects })}
        />
      </div>

      <hr className="border-grayscale-100" />

      <EffectsSection
        effects={overlay.effects}
        onChange={(effects: EffectsProps) => onUpdate({ effects })}
        hideStroke
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Misc
// ---------------------------------------------------------------------------

function NumericFieldWithUnit({
  value,
  unit,
  min,
  max,
  onChange,
}: {
  value: number;
  unit: string;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center rounded-lg border border-grayscale-200 bg-white">
      <button
        type="button"
        onClick={() => onChange(Math.max(min, value - 1))}
        className="flex h-9 w-7 items-center justify-center text-grayscale-500 hover:text-grayscale-800"
      >
        −
      </button>
      <input
        type="text"
        inputMode="numeric"
        value={String(value)}
        onChange={(e) => {
          const raw = Number(e.target.value);
          if (!Number.isFinite(raw)) return;
          onChange(Math.min(max, Math.max(min, raw)));
        }}
        className="w-full min-w-0 border-x border-transparent bg-transparent py-1 text-center text-sm text-grayscale-800 focus:outline-none"
      />
      <span className="px-1 text-[10px] text-grayscale-400">{unit}</span>
      <button
        type="button"
        onClick={() => onChange(Math.min(max, value + 1))}
        className="flex h-9 w-7 items-center justify-center text-grayscale-500 hover:text-grayscale-800"
      >
        +
      </button>
    </div>
  );
}

function OverlaySelectorRow({
  state,
  onSelect,
}: {
  state: EditorState;
  onSelect: (id: string | null) => void;
}) {
  const sorted = [...state.overlays].sort(
    (a, b) => b.layerIndex - a.layerIndex,
  );
  return (
    <div className="border-t border-grayscale-200 p-2">
      <div className="flex flex-wrap gap-1">
        {sorted.map((o) => (
          <button
            key={o.id}
            type="button"
            onClick={() => onSelect(o.id)}
            className={cn(
              "rounded border px-2 py-1 text-[10px]",
              state.selectedOverlayId === o.id
                ? "border-heimdex-navy-400 bg-grayscale-10 text-heimdex-navy-500"
                : "border-grayscale-200 text-grayscale-500 hover:bg-grayscale-10",
            )}
          >
            {o.kind === "text"
              ? `T: ${(o as EditorTextOverlay).text.slice(0, 12) || "…"}`
              : "BG"}
          </button>
        ))}
      </div>
    </div>
  );
}
