"use client";

import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { Dropdown } from "../primitives/Dropdown";
import { ActionBar } from "./ActionBar";
import { BackgroundToolbar } from "./BackgroundToolbar";
import { EffectsSection, StrokeBlock } from "./EffectsSection";
import { TextToolbar } from "./TextToolbar";
import { TransformSection } from "./TransformSection";
import { useOverlaySelection } from "../../hooks/useOverlaySelection";
import { usePresets } from "../../hooks/usePresets";
import { t } from "../../lib/i18n/strings";
import {
  createDefaultBackgroundOverlay,
  createDefaultTextOverlay,
} from "../../lib/overlay-defaults";
import { runOneTimePresetMigration } from "../../lib/preset-migration";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
  EditorOverlayKind,
  EditorTextOverlay,
  EffectsProps,
  TransformProps,
} from "../../lib/overlay-types";
import type { EditorState } from "../../lib/types";

const FONT_OPTIONS = [
  { value: "Pretendard", label: "Pretendard" },
  { value: "Noto Sans KR", label: "Noto Sans KR" },
] as const;

interface OverlayPanelProps {
  state: EditorState;
  onAddTextOverlay: () => void;
  // figma 1602:40004 (배경 섹션) — 단색 배경 추가 버튼은 색상 팔레트
  // 팝업을 띄우고, 선택한 색이 신규 background overlay 의 fillColor 로
  // 주입된다. 인자가 없으면 기본 색이 적용된다.
  onAddBackgroundOverlay: (fillColor?: string) => void;
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

  // Selected overlay only counts when its kind matches the current tab.
  // When no overlay is selected we still render the full control surface
  // (figma 1663:45752 expects controls present at all times) — the
  // editor body just binds to a stable default overlay so the inputs
  // show sensible default values and onUpdate is a no-op until the user
  // explicitly adds an overlay via the "+ 텍스트 추가" / "+ 단색 배경
  // 추가" button or selects an existing one in the timeline / preview.
  const selectedForTab =
    selected && selected.kind === tab ? selected : null;

  // Stable defaults so the controls render with stable identities. startMs
  // = 0 is meaningless here because the overlay never enters state — these
  // objects only feed the editor body's value props.
  const defaultTextOverlay = useMemo(
    () => createDefaultTextOverlay({ startMs: 0 }),
    [],
  );
  const defaultBgOverlay = useMemo(
    () => createDefaultBackgroundOverlay({ startMs: 0 }),
    [],
  );

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
          onAddText={onAddTextOverlay}
          onAddBackground={onAddBackgroundOverlay}
        />

        {tab === "text" ? (
          <TextEditingBody
            overlay={
              (selectedForTab as EditorTextOverlay | null) ?? defaultTextOverlay
            }
            onUpdate={(updates) => {
              if (selectedForTab) onUpdateOverlay(selectedForTab.id, updates);
            }}
            isPlaceholder={selectedForTab == null}
          />
        ) : (
          <BackgroundEditingBody
            overlay={
              (selectedForTab as EditorBackgroundOverlay | null) ??
              defaultBgOverlay
            }
            onUpdate={(updates) => {
              if (selectedForTab) onUpdateOverlay(selectedForTab.id, updates);
            }}
            onReorder={(direction) => {
              if (selectedForTab)
                onReorderOverlay(selectedForTab.id, direction);
            }}
            isPlaceholder={selectedForTab == null}
          />
        )}

        {/* PresetSection (inline preset save + apply inside the wrapper) was
            dropped per the 2026-05-18 goal capture. The GNB TemplateSaveMenu
            and the right wrapper's 템플릿 tab already cover the same surface,
            so keeping a third inline entrypoint just created conflicts.
            presetsApi itself is preserved because the GNB still calls it. */}
      </div>

      {/* OverlaySelectorRow (every-overlay chip strip) was pulled on
          2026-05-18 — once auto-subtitle wiring added many text overlays
          per session, the row filled the right wrapper with ``T: ...``
          tags, which the user surfaced as a regression. Selecting a
          different overlay still works via the preview / left subtitle
          list, so the chip strip wasn't carrying weight either. */}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Text editing body
// ---------------------------------------------------------------------------

function TextEditingBody({
  overlay,
  onUpdate,
  isPlaceholder = false,
}: {
  overlay: EditorTextOverlay;
  onUpdate: (updates: Partial<EditorTextOverlay>) => void;
  // figma 1663:45752 — when no overlay is selected the controls still
  // render with default values; isPlaceholder dims the surface so it's
  // visually clear inputs won't persist until an overlay is added.
  isPlaceholder?: boolean;
}) {
  return (
    <div className={cn("space-y-4", isPlaceholder && "opacity-60")}>
      <textarea
        value={overlay.text}
        onChange={(e) => onUpdate({ text: e.target.value.slice(0, 500) })}
        placeholder={t.text.contentPlaceholder}
        rows={4}
        maxLength={500}
        readOnly={isPlaceholder}
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
  isPlaceholder = false,
}: {
  overlay: EditorBackgroundOverlay;
  onUpdate: (updates: Partial<EditorBackgroundOverlay>) => void;
  onReorder: (direction: "front" | "back" | "forward" | "backward") => void;
  isPlaceholder?: boolean;
}) {
  return (
    <div className={cn("space-y-4", isPlaceholder && "opacity-60")}>
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
