"use client";

/**
 * useOverlaySelection — single source of truth for "which overlay is the
 * panel + preview currently editing".
 *
 * Encapsulates the lookup so components don't `find()` over state.overlays
 * inline — keeps selection state changes in one place + makes refactoring
 * to a Map-keyed store later trivial.
 */

import { useMemo } from "react";

import type { EditorState } from "../lib/types";
import type { EditorOverlay, EditorOverlayKind } from "../lib/overlay-types";

interface OverlaySelection {
  selected: EditorOverlay | null;
  selectedKind: EditorOverlayKind | null;
  isSelected: (id: string) => boolean;
  // Sorted back→front, ready for the overlay layer dropdown.
  byLayer: EditorOverlay[];
}

export function useOverlaySelection(state: EditorState): OverlaySelection {
  const selected = useMemo(() => {
    if (state.selectedOverlayId == null) return null;
    return (
      state.overlays.find((o) => o.id === state.selectedOverlayId) ?? null
    );
  }, [state.overlays, state.selectedOverlayId]);

  const byLayer = useMemo(
    () => [...state.overlays].sort((a, b) => a.layerIndex - b.layerIndex),
    [state.overlays],
  );

  const isSelected = (id: string) => state.selectedOverlayId === id;

  return {
    selected,
    selectedKind: selected?.kind ?? null,
    isSelected,
    byLayer,
  };
}
