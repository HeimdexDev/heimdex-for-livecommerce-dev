"use client";

// figma: 1602:41198 (배경 섹션)
//
// Background tab content rendered as the RightPanel's backgroundTab. This
// used to be a self-contained mock with its own state — none of the
// controls were wired to the editor reducer, which is why "the background
// section looked unchanged" after we redesigned BackgroundEditingBody:
// the user always saw V1's local-state UI, never V2's. This file is now a
// thin wrapper that drives the editor reducer through the same V2
// primitives the OverlayPanel uses (ActionBar + BackgroundEditingBody).

import { useMemo } from "react";

import { ActionBar } from "./OverlayPanel/ActionBar";
import { BackgroundEditingBody } from "./OverlayPanel";
import { createDefaultBackgroundOverlay } from "../lib/overlay-defaults";
import type {
  EditorBackgroundOverlay,
  EditorOverlay,
} from "../lib/overlay-types";
import type { EditorState } from "../lib/types";

interface BackgroundPanelProps {
  state: EditorState;
  onAddSolidBackground: (fillColor?: string) => void;
  onAddImageBackground: (imageUrl: string) => void;
  onUpdateOverlay: (id: string, updates: Partial<EditorOverlay>) => void;
  onReorderOverlay: (
    id: string,
    direction: "front" | "back" | "forward" | "backward",
  ) => void;
}

export function BackgroundPanel({
  state,
  onAddSolidBackground,
  onAddImageBackground,
  onUpdateOverlay,
  onReorderOverlay,
}: BackgroundPanelProps) {
  // Resolve the currently selected background overlay; fall back to a
  // stable default so the controls always render and the user sees the
  // section layout even before adding their first background.
  const selectedOverlay = state.selectedOverlayId
    ? state.overlays.find((o) => o.id === state.selectedOverlayId) ?? null
    : null;
  const selectedBg =
    selectedOverlay && selectedOverlay.kind === "background"
      ? (selectedOverlay as EditorBackgroundOverlay)
      : null;

  const defaultBg = useMemo(
    () => createDefaultBackgroundOverlay({ startMs: 0 }),
    [],
  );

  return (
    <div className="flex flex-col gap-4 p-4">
      <ActionBar
        kind="background"
        onAddText={() => {}}
        onAddBackground={onAddSolidBackground}
        onAddImage={onAddImageBackground}
      />
      <BackgroundEditingBody
        overlay={selectedBg ?? defaultBg}
        onUpdate={(updates) => {
          if (selectedBg) onUpdateOverlay(selectedBg.id, updates);
        }}
        onReorder={(direction) => {
          if (selectedBg) onReorderOverlay(selectedBg.id, direction);
        }}
        isPlaceholder={selectedBg == null}
      />
    </div>
  );
}
